from __future__ import annotations

import math
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_box(value: list[float]) -> list[float]:
    if len(value) != 4 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in value):
        raise ValueError("bbox 必须为 4 个有限的 0～1 归一化坐标")
    if value[0] >= value[2] or value[1] >= value[3]:
        raise ValueError("bbox 必须 x_min < x_max 且 y_min < y_max，不允许零面积")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class VisibleObject(StrictModel):
    object_id: str
    label: str
    bbox: list[float] | None
    confidence: Annotated[float, Field(ge=0, le=1)] | None

    @field_validator("bbox")
    @classmethod
    def box(cls, value):
        return validate_box(value) if value is not None else None


class SceneLabel(StrictModel):
    label: str
    evidence: str


class Light(StrictModel):
    phenomena: list[str]
    backlight: Literal["yes", "no", "unknown"]
    brightness_relations: str


class Motion(StrictModel):
    visible_clues: list[str]
    inferences: list[str]


class Observation(StrictModel):
    scene_labels: list[SceneLabel]
    objects: list[VisibleObject]
    subject_candidates: list[str]
    main_subject_id: str | None
    main_subject_determined: bool
    environment: Literal["indoor", "outdoor", "mixed", "unknown"]
    light: Light
    motion: Motion
    composition_clues: list[str]
    uncertainties: list[str]
    clarification_questions: list[str]

    @field_validator("objects")
    @classmethod
    def unique_objects(cls, values):
        if len({v.object_id for v in values}) != len(values):
            raise ValueError("object_id 必须唯一")
        return values


class Proposal(StrictModel):
    action_type: Literal["crop", "camera_position", "focal_length", "reshoot"]
    goal: str
    actions: list[str]
    reasons: list[str]
    tradeoffs: list[str]
    conditions: list[str]
    limitations: list[str]
    parameters: list[str] | None


class Advice(StrictModel):
    observation: Observation
    user_goal: str
    equipment_facts: list[str]
    unknown_conditions: list[str]
    proposals: Annotated[list[Proposal], Field(min_length=2, max_length=3)]


class Price(StrictModel):
    input_per_million: float | None = Field(default=None, ge=0)
    output_per_million: float | None = Field(default=None, ge=0)
    cache_per_million: float | None = Field(default=None, ge=0)
    cache_write_per_million: float | None = Field(default=None, ge=0)
    currency: Literal["CNY", "USD"] = "CNY"
    source_url: str = ""
    checked_on: str = ""
    limitations: str = "仅 token 估算；不覆盖阶梯、图片独立计费等特殊项目，以账单为准。"


class ModelConfig(StrictModel):
    config_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    provider: str
    protocol: Literal["mock", "chat", "responses", "anthropic", "gemini"]
    base_url: str = ""
    model_id: str = ""
    key_env: str = ""
    timeout: float = Field(default=60.0, ge=1, le=600)
    max_output: int = Field(default=4096, ge=128, le=65536)
    detail: Literal["omit", "auto", "low", "high"] = "omit"
    structured: Literal["prompt", "json_object", "json_schema"] = "prompt"
    reasoning: Literal[
        "omit", "enable_thinking", "thinking_type", "effort", "budget_tokens", "thinking_budget"
    ] = "omit"
    reasoning_value: str = ""
    mock_case: Literal["correct", "omission", "malformed", "invalid_box", "failure"] = "correct"
    price: Price = Field(default_factory=Price)

    @field_validator("base_url")
    @classmethod
    def public_url(cls, value):
        if value:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Base URL 必须为 http(s)，不得带凭据、查询参数或片段")
        return value.rstrip("/")


class Usage(StrictModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    output_includes_reasoning: bool = True
    input_includes_cache: bool = True
    details: dict = Field(default_factory=dict)


class ErrorItem(StrictModel):
    tag: str
    model_conclusion: str = ""
    human_confirmation: str = "无法判定"
    severity: Literal["轻微", "中等", "严重", "无法判定"] = "无法判定"
    evidence: str = ""
    suspected_cause: str = ""


class Evaluation(StrictModel):
    reviewed: bool = False
    scores: dict[str, int | None] = Field(default_factory=dict)
    errors: list[ErrorItem] = Field(default_factory=list)
    correct_notes: str = ""
    box_matches: dict[str, str] = Field(default_factory=dict)


class Reference(StrictModel):
    scene_labels: list[str] = Field(default_factory=list)
    scene_annotated: bool = False
    objects: list[VisibleObject] = Field(default_factory=list)
    notes: str = ""


class ModelResult(StrictModel):
    result_id: str = Field(default_factory=lambda: uuid4().hex)
    config: ModelConfig
    status: str
    call_success: bool
    format_pass: bool
    raw_answer: str = ""
    parsed: dict | None = None
    actual_model: str | None = None
    usage: Usage = Field(default_factory=Usage)
    elapsed_seconds: float = 0
    error: str | None = None
    attempts: list[dict] = Field(default_factory=list)
    cost: dict | None = None


class RunRecord(StrictModel):
    schema_version: str = "1"
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str
    mode: Literal["recognition", "advice"]
    experiment_version: str
    dataset_split: Literal["开发", "验证"]
    image: dict
    prompt: str
    prompt_version: str
    prompt_sha256: str
    context: dict
    results: list[ModelResult]
    reference: Reference = Field(default_factory=Reference)
    evaluations: dict[str, Evaluation] = Field(default_factory=dict)
    sample_file: str | None = None
