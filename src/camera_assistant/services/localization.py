"""Local DINO detection on the exact JPEG already supplied to the vision model."""
from __future__ import annotations

import atexit
import base64
import hashlib
import io

from PIL import Image

from camera_assistant.config import PROJECT_ROOT, Settings
from camera_assistant.models import ImageInspection, SceneAnalysis, UserRequest
from vision_lab_tool.detector_models import DetectorConfig, MethodResult, VLMSnapshot
from vision_lab_tool.detector_queries import compose_queries
from vision_lab_tool.detector_runner import associate_detection
from vision_lab_tool.detectors.client import DetectorClient
from vision_lab_tool.images import PreparedImage
from vision_lab_tool.models import ModelConfig


class GroundingDinoLocalizer:
    def __init__(self, settings: Settings, client: DetectorClient | None = None) -> None:
        self.settings = settings
        self.client = client or DetectorClient(PROJECT_ROOT, python=settings.detector_python)
        atexit.register(self.client.stop_worker)
        self.config = DetectorConfig(
            detector="grounding_dino", model_id="IDEA-Research/grounding-dino-tiny",
            weights_path=settings.detector_weights_path, revision=settings.detector_revision,
            device=settings.detector_device, precision="float32",
            box_threshold=settings.detector_box_threshold,
            text_threshold=settings.detector_text_threshold,
            timeout_seconds=settings.detector_timeout_seconds,
        )

    def localize(self, inspection: ImageInspection, request: UserRequest,
                 scene: SceneAnalysis) -> MethodResult:
        sent_bytes = base64.b64decode(inspection.model_image_data_url.split(",", 1)[1], validate=True)
        with Image.open(io.BytesIO(sent_bytes)) as image:
            corrected = image.convert("RGB")
        digest = hashlib.sha256(sent_bytes).hexdigest()
        prepared = PreparedImage(
            corrected=corrected, sent_bytes=sent_bytes,
            original_size=(inspection.metrics.width, inspection.metrics.height),
            original_format="JPEG", original_sha256=digest, corrected_sha256=digest,
            longest_edge=1600, quality=88, exif={},
        )
        queries = compose_queries(request.intent, scene.objects)
        detection = self.client.detect(prepared, queries["merged"], self.config)
        snapshot = VLMSnapshot(
            config=ModelConfig(
                name=self.settings.vision_model, provider="生产视觉模型", protocol="chat",
                model_id=self.settings.vision_model, base_url=self.settings.base_url,
            ),
            status="success", semantic_status="success", selection_status="success",
            subject_status=scene.subject_status, semantics=scene.objects,
            main_subject_ids=scene.main_subject_ids,
        )
        return associate_detection(detection, snapshot, queries)
