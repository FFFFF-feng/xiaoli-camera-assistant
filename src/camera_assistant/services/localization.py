"""Local DINO detection on the exact JPEG already supplied to the vision model."""
from __future__ import annotations

import atexit
import base64
import hashlib
import io

from PIL import Image

from camera_assistant.config import PROJECT_ROOT, Settings
from camera_assistant.models import ImageInspection, SceneAnalysis, UserRequest
from camera_assistant.services.photography_targets import (
    compose_photography_queries,
    resolve_photography_scope,
)
from vision_lab_tool.detector_models import (
    DetectionResult,
    DetectorConfig,
    MethodResult,
    SubjectSelection,
)
from vision_lab_tool.detector_queries import canonical, label_components
from vision_lab_tool.detectors.client import DetectorClient
from vision_lab_tool.images import PreparedImage

ASSOCIATION_RULE_VERSION = "production-photography-association-v4"


def _associate_photography(detection: DetectionResult, scene: SceneAnalysis,
                          queries: dict) -> MethodResult:
    """Bind geometry only when every required semantic target is complete/unique.

    Physical identity remains a VLM claim in the association record. The local
    category box supplies geometry, never reflection/depiction/entity truth.
    """
    objects = [obj.model_copy(deep=True) for obj in detection.filtered_candidates]
    detector_entity_claims = {obj.object_id: obj.entity_kind for obj in objects}
    for obj in objects:
        obj.entity_kind = "unknown"
    queries = dict(queries)
    scope = resolve_photography_scope(queries["task_text"], scene.objects, scene.main_subject_ids)
    queries["task_scope"] = scope
    normalized = {obj.object_id: label_components(obj.label_original, queries["merged"])
                  for obj in objects}
    queries["label_normalization"] = normalized
    roles = {role["object_id"]: role for role in scope["object_roles"]}
    associations, uses, selected, covered, matched_main = [], {}, [], set(), set()
    for sem in scene.objects:
        query = canonical(sem.query)
        matches = [obj for obj in objects if normalized[obj.object_id]["components"] == [query]
                   and sem.target_level != "unknown" and obj.target_level != "unknown"
                   and (obj.target_level == sem.target_level or (
                       obj.target_level == "instance" and sem.target_level in {"whole", "instance"}))]
        association = {"vlm_object_id": sem.object_id, "query": query,
                       "query_original": sem.query, "scope_role": roles[sem.object_id]["role"],
                       "scope_evidence": roles[sem.object_id]["evidence"],
                       "candidate_ids": [obj.object_id for obj in matches],
                       "status": "unique_class" if len(matches) == 1 else "ambiguous_or_missing",
                       "semantic_target_level": sem.target_level,
                       "semantic_entity_kind": sem.entity_kind,
                       "detector_entity_claims": {
                           obj.object_id: detector_entity_claims[obj.object_id] for obj in matches},
                       "entity_evidence_source": "vlm_semantic_claim_only",
                       "basis": "complete exact class+compatible level; no score/area selection"}
        associations.append(association)
        if len(matches) == 1:
            obj = matches[0]
            uses.setdefault(obj.object_id, []).append(sem.object_id)
            covered.add(sem.object_id)
            if (sem.object_id in scene.main_subject_ids
                    and sem.entity_kind in {"physical", "unknown"}
                    and detector_entity_claims[obj.object_id] in {"physical", "unknown"}):
                selected.append(obj.object_id)
                matched_main.add(sem.object_id)
    for association in associations:
        if any(len(uses.get(value, [])) > 1 for value in association["candidate_ids"]):
            association["status"] = "ambiguous_shared_candidate"
            covered.discard(association["vlm_object_id"])
    required = {role["object_id"] for role in scope["object_roles"] if role["required"]}
    omitted_required = required - set(scene.main_subject_ids)
    scope["required_targets_missing_from_main_ids"] = sorted(omitted_required)
    uncertainty = []
    if scope["intent_parse_uncertainties"] or not scope["required_units"]:
        uncertainty.append("intent_parse")
    if any(unit["unit_id"] in scope["missing_semantic_units"] and not unit.get("unresolved")
           for unit in scope["required_units"]) or omitted_required:
        uncertainty.append("semantic_coverage")
    if scope["all_instances_requested"]:
        uncertainty.append("instance_count")
    if scope["location_constraints"]:
        uncertainty.append("location_identity")
    required_associations = [item for item in associations if item["vlm_object_id"] in required]
    if any(len(item["candidate_ids"]) > 1 for item in required_associations):
        uncertainty.append("detector_multiple_candidates")
    if any(not item["candidate_ids"] for item in required_associations):
        uncertainty.append("detector_missing_geometry")
    if any(len(ids) > 1 for ids in uses.values()):
        uncertainty.append("shared_candidate")
    if scope["entity_identity_requested"] or any(
            sem.object_id in scene.main_subject_ids and sem.entity_kind not in {"physical", "unknown"}
            for sem in scene.objects):
        uncertainty.append("entity_identity")
    if scene.subject_status != "selected":
        uncertainty.append("vision_subject_uncertain")
    scope["selection_uncertainty"] = uncertainty
    if detection.status not in {"success", "ok"}:
        state, reason = "abstained", "检测阶段未提供完整可靠坐标，保留候选并弃权"
    elif scene.subject_status in {"abstained", "ambiguous"}:
        state, reason = scene.subject_status, "视觉语义没有可靠主体选择，保留检测候选"
    elif scope["status"] != "known" or scope["missing_semantic_units"] or required - covered:
        state = "ambiguous"
        reason = ("拍摄意图存在未解析要求；已保留原文，不能等同于检测多候选" if "intent_parse" in uncertainty
                  else "同类目标存在多个检测候选；禁止按分数或面积强行选择" if
                  "detector_multiple_candidates" in uncertainty else
                  "用户位置或环境约束尚未核验，类别框不能证明对应身份" if
                  "location_identity" in uncertainty else
                  "用户必需目标、数量或层级尚未获得完整唯一证据")
    elif omitted_required:
        state, reason = "ambiguous", "VLM主体集合遗漏用户明确必需目标；完整保护集无法成立"
    elif any(len(ids) > 1 for ids in uses.values()):
        state, reason = "ambiguous", "多个语义实例引用同一候选，禁止复用几何框"
    elif scope["entity_identity_requested"]:
        state, reason = "ambiguous", "类别框不能证明任务要求的倒影、图绘或模型实体归属"
    elif (scene.main_subject_ids and matched_main == set(scene.main_subject_ids)
          and len(selected) == len(set(selected))):
        state, reason = "selected", "任务明确支持每个主目标且类别与层级唯一匹配；实体归属仍为语义声明"
    else:
        state, reason = "ambiguous" if objects else "abstained", "主目标无完整唯一几何关联"
    return MethodResult(method="B1", detector=detection.config.detector, status=detection.status,
        candidates=objects, detection=detection, queries=queries,
        selection=SubjectSelection(status=state, selected_ids=selected if state == "selected" else [],
            candidate_ids=[obj.object_id for obj in objects], rule_version=ASSOCIATION_RULE_VERSION,
            reason=reason, associations=associations),
        stages={"detector": detection.status, "semantics": "success", "selection": state},
        diagnostics=detection.diagnostics.copy(), timings=detection.timings.copy(), real=detection.real)


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
        queries = compose_photography_queries(request.intent, scene.objects)
        if not queries["merged"]:
            detection = DetectionResult(config=self.config, status="query_missing",
                diagnostics=["任务和视觉语义均未提供合法英文类别，跳过本地推理。"])
        else:
            detection = self.client.detect(prepared, queries["merged"], self.config)
        return _associate_photography(detection, scene, queries)
