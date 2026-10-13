"""YOLO26n fixed-class detector, official Results already restore sent-image pixels."""
from __future__ import annotations

import time
from uuid import uuid4

from .base import finish_result, pixel_xyxy, provenance, weights_path


class UltralyticsYOLO:
    def __init__(self, config):
        started = time.perf_counter()
        from ultralytics import YOLO
        from ultralytics.models.yolo.detect.predict import DetectionPredictor

        path = weights_path(config)
        if path.name != "yolo26n.pt":
            raise ValueError("首版固定类别对照仅允许官方检测权重 yolo26n.pt。")
        # Existing absolute path prevents Ultralytics' auto-download fallback.
        self.model = YOLO(str(path), task="detect")
        if self.model.task != "detect":
            raise ValueError("权重 task 不是 detect，不允许 seg/pose/obb 混用。")
        self.metadata = provenance(config)
        self.load_seconds = time.perf_counter() - started
        adapter = self

        class ProvenancePredictor(DetectionPredictor):
            def postprocess(self, preds, img, orig_imgs, **kwargs):
                value = preds[0] if isinstance(preds, (tuple, list)) else preds
                adapter.capture["input_shape"] = list(img.shape)
                adapter.capture["head_output"] = value.detach().float().cpu().tolist()
                return super().postprocess(preds, img, orig_imgs, **kwargs)

        self.predictor_type = ProvenancePredictor

    def detect(self, image, queries, config, *, cold=False):
        import numpy as np
        import torch

        started = time.perf_counter()
        self.capture = {}
        if config.device.startswith("cuda"):
            torch.cuda.synchronize(config.device)
        # PIL -> ndarray uses RGB, whereas ndarray Ultralytics input is BGR.
        source = np.asarray(image)[:, :, ::-1].copy()
        result = self.model.predict(
            source=source, conf=0.0, imgsz=config.imgsz, device=config.device,
            half=config.precision == "float16", batch=1, nms=False,
            rect=True, max_det=300, verbose=False, save=False,
            predictor=self.predictor_type,
        )[0]
        captured = self.capture
        if config.device.startswith("cuda"):
            torch.cuda.synchronize(config.device)
        completed = time.perf_counter()
        if tuple(result.orig_shape) != image.size[::-1]:
            raise RuntimeError("YOLO orig_shape 与同份发送 JPEG 尺寸不一致。")
        raw = []
        boxes = result.boxes
        shape = captured.get("input_shape", [])
        heads = captured.get("head_output")
        if not shape or not heads or len(heads) != 1 or any(len(row) != 6 for row in heads[0]):
            raise RuntimeError("YOLO26 nms=False 原始输出不是 batch x 300 x 6；锁定契约不匹配。")
        head_rows = heads[0]
        # Exact locked ops.scale_boxes contract, recorded for provenance only.
        # Results.xyxy itself is never inverse-scaled a second time.
        gain = min(shape[-2] / image.height, shape[-1] / image.width)
        new_h, new_w = round(image.height * gain), round(image.width * gain)
        gains = [new_w / image.width, new_h / image.height]
        pads = [round((shape[-1] - new_w) / 2 - 0.1),
                round((shape[-2] - new_h) / 2 - 0.1)]
        unmatched = set(range(len(head_rows)))
        for index, (box, confidence, class_id) in enumerate(zip(
                boxes.xyxy.float().cpu().tolist(), boxes.conf.float().cpu().tolist(),
                boxes.cls.int().cpu().tolist())):
            original_index = next((candidate for candidate in sorted(unmatched)
                                   if abs(head_rows[candidate][4] - confidence) < 1e-7
                                   and int(head_rows[candidate][5]) == class_id), None)
            if original_index is None:
                raise RuntimeError("YOLO 原始输出与 Results 类别/分数无法一对一对应。")
            unmatched.remove(original_index)
            native = head_rows[original_index][:4]
            unclipped = [(native[i] - pads[i % 2]) / gains[i % 2] for i in range(4)]
            try:
                pixel_xyxy(unclipped, *image.size)
                valid = True
            except ValueError:
                valid = False
            clipped = any(abs(left - right) > 1e-3 for left, right in zip(unclipped, box))
            raw.append({"raw_index": original_index, "label_original": result.names[class_id],
                        "class_id": class_id, "score": confidence,
                        "score_kind": "yolo_detection_confidence",
                        "bbox_native": native, "bbox_postprocessed": box,
                        "bbox_sent_before_library_clipping": unclipped,
                        "official_clipped": clipped, "raw_coordinates_valid": valid,
                        "native_coordinate_format": "model_input_pixel_xyxy",
                        "coordinate_basis": "ultralytics_Results_boxes_xyxy_sent_jpeg",
                        "passes_confidence": confidence >= config.confidence})
        selected = [item for item in raw if item["passes_confidence"]]
        metadata = {**self.metadata, "queries": queries, "queries_used_for_inference": False,
                    "fixed_class_names": result.names, "actual_input_size": shape,
                    "orig_shape_hw": list(result.orig_shape), "imgsz": config.imgsz,
                    "nms": False, "rect": True, "max_det": 300,
                    "thresholds": {"confidence": config.confidence},
                    "preprocessing": "RGB PIL -> BGR ndarray -> official LetterBox(rect=True)",
                    "raw_head_output": captured.get("head_output"),
                    "raw_head_coordinate_space": "model input pixel xyxy (native end2end head)",
                    "resize_xy": gains, "pad_xy": pads, "crop_offset_xy": [0, 0],
                    "official_clipped_count": sum(item["official_clipped"] for item in raw),
                    "raw_candidate_scope": "all Results candidates at conf=0; native head preserved",
                    "padding_reversed_again": False, "model_cache_hit": not cold,
                    "library_speed_ms": result.speed}
        return finish_result(config, uuid4().hex, raw, selected, image.size, metadata,
                             {"load": self.load_seconds if cold else 0.0,
                              "preprocess": result.speed.get("preprocess", 0) / 1000,
                              "inference": result.speed.get("inference", 0) / 1000,
                              "postprocess": result.speed.get("postprocess", 0) / 1000,
                              "total": completed - started +
                              (self.load_seconds if cold else 0.0)})
