"""Lazy local-only MobileSAM vit_t backend. Checkpoint is never downloaded here."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .contracts import BackendError, MaskCandidates


class MobileSAMBackend:
    backend = "mobile_sam"
    model_version = "MobileSAM-vit_t"
    preprocessing_version = "sam-ResizeLongestSide1024-RGB-normalize-pad-native-logits-v1"

    def __init__(self, weights_path, *, device="cpu", expected_sha256=None):
        self.path = Path(weights_path) if weights_path is not None else None
        self.device = device
        self.expected_sha256 = expected_sha256
        self.weights_sha256 = None
        self._predictor = None
        self._torch = None

    def load(self):
        if self.path is None or not self.path.is_file():
            raise BackendError("weights_missing")
        if self.path.stat().st_size == 0:
            raise BackendError("weights_invalid")
        # Hash only a real local file, before any deserialization.
        with self.path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if self.expected_sha256 and digest.lower() != self.expected_sha256.lower():
            raise BackendError("weights_invalid")
        try:
            import torch
            from mobile_sam import SamPredictor, sam_model_registry
        except (ImportError, OSError, RuntimeError):
            raise BackendError("backend_unavailable") from None
        if self.device == "cuda":
            if not torch.cuda.is_available():
                raise BackendError("device_unavailable")
            self.device = "cuda:0"
        elif self.device.startswith("cuda:"):
            try:
                index = int(self.device.split(":")[1])
                valid = torch.cuda.is_available() and 0 <= index < torch.cuda.device_count()
            except ValueError:
                valid = False
            if not valid:
                raise BackendError("device_unavailable")
        elif self.device != "cpu":
            raise BackendError("device_unavailable")
        # Load only state dictionaries (no arbitrary checkpoint pickle objects).
        try:
            state = torch.load(str(self.path), map_location="cpu", weights_only=True)
            model = sam_model_registry["vit_t"](checkpoint=None)
            model.load_state_dict(state, strict=True)
        except Exception:  # noqa: BLE001 -- checkpoint errors have a fixed public code
            raise BackendError("weights_invalid") from None
        try:
            model.to(device=self.device)
            model.eval()
            self._predictor = SamPredictor(model)
            self._torch = torch
            self._sync()
            self.weights_sha256 = digest
        except Exception:  # noqa: BLE001 -- native device errors must not leak input text
            self._predictor = None
            raise BackendError("device_unavailable") from None

    def _sync(self):
        if self.device.startswith("cuda"):
            self._torch.cuda.synchronize(self.device)

    def encode(self, rgb):
        with self._torch.inference_mode():
            self._predictor.set_image(rgb, image_format="RGB")
            self._sync()

    def predict(self, box):
        with self._torch.inference_mode():
            masks, scores, _ = self._predictor.predict(box=box, multimask_output=True)
            self._sync()
        return MaskCandidates(masks, scores)

    def reset_image(self):
        if self._predictor is not None:
            self._predictor.reset_image()

    def close(self):
        self.reset_image()
        self._predictor = None
        if self._torch is not None and self.device.startswith("cuda"):
            self._torch.cuda.empty_cache()
        self._torch = None
