"""Locked Transformers contract: native normalized cxcywh -> sent JPEG pixel xyxy."""
from __future__ import annotations

import inspect
import time
from uuid import uuid4

from .base import finish_result, provenance, weights_path


class GroundingDinoHF:
    def __init__(self, config):
        started = time.perf_counter()
        import torch
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        self.torch = torch
        path = str(weights_path(config))
        self.processor = AutoProcessor.from_pretrained(path, local_files_only=True,
                                                      trust_remote_code=False, use_fast=False)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(
            path, local_files_only=True, trust_remote_code=False,
            dtype=torch.float16 if config.precision == "float16" else torch.float32,
        )
        self.model.config.disable_custom_kernels = True
        self.model.to(config.device).eval()
        self.metadata = provenance(config)
        self.load_seconds = time.perf_counter() - started
        self.threshold_key = "threshold"
        parameters = inspect.signature(
            self.processor.post_process_grounded_object_detection).parameters
        if "threshold" not in parameters:
            raise RuntimeError("锁定的 Transformers 后处理契约不匹配：缺少 threshold。")

    def detect(self, image, queries, config, *, cold=False):
        torch = self.torch
        started = time.perf_counter()
        if not queries or any(not query.strip() or not query.isascii() for query in queries):
            raise ValueError("Grounding DINO 首版要求非空英文类别短语查询。")
        prompt = ". ".join(query.strip().strip(".").lower() for query in queries) + "."
        inputs = self.processor(images=image, text=prompt, return_tensors="pt")
        if inputs.input_ids.shape[-1] > self.model.config.max_text_len:
            raise ValueError("查询超过模型 max_text_len；请缩短英文类别清单，避免静默截断。")
        internal_size = list(inputs.pixel_values.shape)
        mask = inputs.get("pixel_mask")
        content_size = ([int(mask[0].any(dim=1).sum()), int(mask[0].any(dim=0).sum())]
                        if mask is not None else internal_size[-2:])
        inputs = inputs.to(config.device)
        if config.precision == "float16":
            inputs["pixel_values"] = inputs["pixel_values"].half()
        self._synchronize(config)
        preprocessed = time.perf_counter()
        with torch.inference_mode():
            outputs = self.model(**inputs)
        self._synchronize(config)
        inferred = time.perf_counter()
        # threshold=0 preserves every native query prediction, then the configured
        # box threshold is applied below. Target sizes are exactly sent JPEG H,W.
        result = self.processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, threshold=0.0,
            text_threshold=config.text_threshold, target_sizes=[image.size[::-1]],
        )[0]
        labels = result.get("text_labels")
        if labels is None:
            labels = result.get("labels")
        if labels is None or any(not isinstance(label, str) for label in labels):
            raise RuntimeError("后处理没有返回文字标签；不把整数 token 索引当作类别。")
        native = outputs.pred_boxes[0].float().cpu().tolist()
        pixels = result["boxes"].float().cpu().tolist()
        scores = result["scores"].float().cpu().tolist()
        if not (len(native) == len(pixels) == len(scores) == len(labels)):
            raise RuntimeError("原始预测与 threshold=0 后处理返回数量不一致。")
        raw = []
        for index, (box, score, label) in enumerate(zip(pixels, scores, labels)):
            raw.append({"raw_index": index, "label_original": label,
                        "class_id": None, "score": score,
                        "score_kind": "grounding_text_similarity_max_sigmoid",
                        "bbox_native": native[index], "bbox_postprocessed": box,
                        "native_coordinate_format": "normalized_cxcywh",
                        "coordinate_basis": "hf_target_sizes_sent_jpeg_pixel_xyxy",
                        "passes_box_threshold": score > config.box_threshold})
        selected = [item for item in raw if item["passes_box_threshold"]]
        completed = time.perf_counter()
        metadata = {**self.metadata, "queries": queries, "prompt": prompt,
                    "actual_input_size": internal_size, "content_size_hw": content_size,
                    "target_sizes_hw": [list(image.size[::-1])],
                    "preprocessing": self.processor.image_processor.to_dict(),
                    "token_count": inputs.input_ids.shape[-1],
                    "postprocessing_contract": "threshold,text_threshold,target_sizes(H,W)",
                    "thresholds": {"box": config.box_threshold, "text": config.text_threshold},
                    "raw_candidate_scope": "all native model queries before box threshold",
                    "padding_reversed_again": False, "model_cache_hit": not cold}
        return finish_result(config, uuid4().hex, raw, selected, image.size, metadata,
                             {"load": self.load_seconds if cold else 0.0,
                              "preprocess": preprocessed - started,
                              "inference": inferred - preprocessed,
                              "postprocess": completed - inferred,
                              "total": completed - started +
                              (self.load_seconds if cold else 0.0)})

    def _synchronize(self, config):
        if config.device.startswith("cuda"):
            self.torch.cuda.synchronize(config.device)
