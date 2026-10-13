"""Separate detector experiment schema; legacy RunRecord v1 is untouched."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from vision_lab_tool.models import ModelConfig, StrictModel, Usage, validate_box

TargetLevel = Literal["whole", "part", "instance", "region", "combination", "unknown"]
EntityKind = Literal["physical", "reflection", "depiction", "mannequin", "scale_model", "unknown"]


class DetectorConfig(StrictModel):
    detector: Literal["grounding_dino", "yolo26"]
    model_id: str = ""
    weights_path: str = ""
    revision: str = ""
    device: str = "cpu"
    precision: Literal["float32", "float16"] = "float32"
    box_threshold: float = Field(default=.35, ge=0, le=1)
    text_threshold: float = Field(default=.25, ge=0, le=1)
    confidence: float = Field(default=.25, ge=0, le=1)
    imgsz: int = Field(default=640, ge=32, le=4096)
    timeout_seconds: float = Field(default=180, ge=1, le=600)
    dedup_iou: float | None = Field(default=None, ge=0, le=1)


class DetectionObject(StrictModel):
    object_id: str
    label_original: str
    label_display: str
    class_id: int | None = None
    score: float | None = None
    score_kind: str = "detection_confidence"
    bbox_native: list[float]
    bbox_postprocessed: list[float]
    bbox: list[float]
    coordinate_basis: str
    target_level: TargetLevel = "instance"
    entity_kind: EntityKind = "unknown"
    parent_object_id: str | None = None
    semantic_source: str = "detector"

    @field_validator("bbox")
    @classmethod
    def box(cls, value):
        return validate_box(value)


class SubjectSelection(StrictModel):
    status: Literal["selected", "ambiguous", "abstained", "unsupported", "detection_only"] = "abstained"
    selected_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    rule_version: str = "conservative-association-v1"
    reason: str = ""
    associations: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.selected_ids)) != len(self.selected_ids):
            raise ValueError("主体 selected_ids 重复")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("主体 candidate_ids 重复")
        return self


class DetectionResult(StrictModel):
    result_id: str = Field(default_factory=lambda: uuid4().hex)
    config: DetectorConfig
    status: str
    raw_candidates: list[dict] = Field(default_factory=list)
    candidates: list[DetectionObject] = Field(default_factory=list)
    filtered_candidates: list[DetectionObject] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    timings: dict[str, float] = Field(default_factory=dict)
    cache_hit: bool = False
    cache_source: str | None = None
    real: bool = True

    @model_validator(mode="after")
    def valid_ids(self):
        ids = [v.object_id for v in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("候选 ID 重复")
        if any(v.object_id not in ids for v in self.filtered_candidates):
            raise ValueError("过滤结果必须引用原候选")
        return self


class SemanticObject(StrictModel):
    object_id: str
    label: str
    query: str
    target_level: TargetLevel = "unknown"
    entity_kind: EntityKind = "unknown"
    parent_object_id: str | None = None


class VLMSnapshot(StrictModel):
    result_id: str = Field(default_factory=lambda: uuid4().hex)
    config: ModelConfig
    status: str = "pending"
    raw_answer: str = ""
    parsed: dict | None = None
    json_status: str = "not_attempted"
    box_status: str = "not_attempted"
    semantic_status: str = "not_attempted"
    subject_status: str = "not_available"
    selection_status: str = "not_attempted"
    semantics: list[SemanticObject] = Field(default_factory=list)
    main_subject_ids: list[str] = Field(default_factory=list)
    candidates: list[DetectionObject] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    cost: dict | None = None
    attempts: list[dict] = Field(default_factory=list)
    elapsed_seconds: float = 0
    actual_model: str | None = None
    error: str | None = None
    cache_hit: bool = False
    cache_source: str | None = None
    real: bool = True
    provenance: dict = Field(default_factory=dict)


class MethodResult(StrictModel):
    result_id: str = Field(default_factory=lambda: uuid4().hex)
    method: Literal["A", "B1", "B2", "detector_only"]
    detector: str = ""
    status: str = "pending"
    candidates: list[DetectionObject] = Field(default_factory=list)
    detection: DetectionResult | None = None
    selection: SubjectSelection = Field(default_factory=SubjectSelection)
    queries: dict = Field(default_factory=dict)
    unsupported_targets: list[str] = Field(default_factory=list)
    stages: dict[str, str] = Field(default_factory=dict)
    timings: dict[str, float] = Field(default_factory=dict)
    diagnostics: list[str] = Field(default_factory=list)
    real: bool = True

    @model_validator(mode="after")
    def binding(self):
        ids = [o.object_id for o in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("方法候选 ID 重复")
        if any(v not in ids for v in self.selection.selected_ids + self.selection.candidate_ids):
            raise ValueError("主体 ID 未绑定到方法候选")
        return self


class GroundTruth(StrictModel):
    gt_id: str
    label: str
    bbox: list[float]
    target_level: TargetLevel = "instance"
    entity_kind: EntityKind = "unknown"
    parent_id: str | None = None
    user_main_subject: bool = False
    required: bool = True
    occluded: bool = False
    truncated: bool = False
    judgeable: bool = True
    ignore: bool = False
    ignore_reason: str = ""
    out_of_scope: bool = False
    annotation_source: str = "human"
    confirmed: bool = False

    @field_validator("bbox")
    @classmethod
    def box(cls, value):
        return validate_box(value)


class DetectorReference(StrictModel):
    complete: bool = False
    objects: list[GroundTruth] = Field(default_factory=list)
    notes: str = ""
    main_subject_judgeable: bool = False
    ambiguity_expected: bool = False
    boundary_required: bool = False
    annotation_policy: str = "confirmed-human-v1"

    @model_validator(mode="after")
    def ids(self):
        ids = [v.gt_id for v in self.objects]
        if len(set(ids)) != len(ids):
            raise ValueError("gt_id 重复")
        if any(v.parent_id and v.parent_id not in ids for v in self.objects):
            raise ValueError("人工框 parent_id 不存在")
        if self.complete and any(not v.confirmed for v in self.objects):
            raise ValueError("参考完整需逐框人工确认")
        return self


class DetectorError(StrictModel):
    error_id: str = Field(default_factory=lambda: uuid4().hex)
    tag: str
    source: str = "human"
    model_conclusion: str = ""
    human_confirmation: str = "待确认"
    confirmed: bool = False
    evidence: str = ""
    severity: str = "无法判定"
    suspected_cause: str = ""


class DetectorReview(StrictModel):
    reviewed: bool = False
    box_matches: dict[str, str] = Field(default_factory=dict)
    human_selected_ids: list[str] = Field(default_factory=list)
    subject_correct_auto: bool | None = None
    subject_correct_human: bool | None = None
    query_covered_gt_ids: list[str] | None = None
    query_covered_gt_ids_by_source: dict[str, list[str]] = Field(default_factory=dict)
    support_gt_ids: list[str] | None = None
    in_scope_pred_ids: list[str] | None = None
    ignored_pred_ids: list[str] = Field(default_factory=list)
    edge_preserved: bool | None = None
    errors: list[DetectorError] = Field(default_factory=list)
    notes: str = ""


class DetectorExperiment(StrictModel):
    schema_version: Literal["detector-1"] = "detector-1"
    experiment_id: str = Field(default_factory=lambda: uuid4().hex)
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    attempt_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    mode: Literal["pure_detection", "localization"]
    experiment_version: str
    dataset_split: Literal["开发", "验证"] = "开发"
    task_prompt: str
    task_prompt_sha256: str
    dictionary_version: str = "task-english-v1"
    image: dict
    configs: list[DetectorConfig]
    vlm: VLMSnapshot | None = None
    results: list[MethodResult] = Field(default_factory=list)
    reference: DetectorReference = Field(default_factory=DetectorReference)
    evaluations: dict[str, DetectorReview] = Field(default_factory=dict)
    stages: dict[str, str] = Field(default_factory=dict)
    timings: dict[str, float] = Field(default_factory=dict)
    simulated: bool = False
    sample_file: str | None = None
    costs: dict = Field(default_factory=dict)
    provenance: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def ids(self):
        if len({v.result_id for v in self.results}) != len(self.results):
            raise ValueError("result_id 重复")
        return self
