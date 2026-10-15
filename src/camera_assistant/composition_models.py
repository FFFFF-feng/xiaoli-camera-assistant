"""Composition suggestions with explicit actions and traceable knowledge references."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from camera_assistant.candidate_models import (
    CandidateOperation,
    FieldCheck,
    TrialAction,
    candidate_list,
)
from camera_assistant.knowledge_citation_models import KnowledgeCitation, KnowledgeCitationReview


class CompositionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CompositionProposal(CompositionModel):
    action_type: Literal["crop", "camera_position", "focal_length", "reshoot"]
    goal: str = Field(min_length=1)
    actions: list[str] = Field(min_length=1)
    reasons: list[str] = Field(min_length=1)
    tradeoffs: list[str] = Field(min_length=1)
    conditions: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    knowledge_ids: list[str] = Field(default_factory=list)
    knowledge_citations: list[KnowledgeCitation | dict] = Field(default_factory=list)
    knowledge_citation_review: KnowledgeCitationReview | None = None
    crop_bbox: list[float] | None = None
    candidate_operations: list[CandidateOperation] = Field(default_factory=list)
    reviewed_operations: list[CandidateOperation] = Field(default_factory=list)
    action_evidence: list[str] = Field(default_factory=list)
    trial_actions: list[TrialAction] = Field(default_factory=list)
    field_checks: list[FieldCheck] = Field(default_factory=list)

    @field_validator("knowledge_citations", mode="before")
    @classmethod
    def isolate_citation_metadata(cls, value: object) -> list[KnowledgeCitation | dict]:
        from camera_assistant.services.knowledge_citations import citation_candidates

        return citation_candidates(value)

    @field_validator("candidate_operations", mode="before")
    @classmethod
    def isolate_candidate_metadata(cls, value: object) -> list[CandidateOperation]:
        return candidate_list(value)

    @field_validator("reviewed_operations", mode="before")
    @classmethod
    def ignore_model_review_claims(cls, value: object) -> list[CandidateOperation]:
        return []

    @field_validator("goal")
    @classmethod
    def nonblank_goal(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("构图目标不能为空白。")
        return value.strip()

    @field_validator("actions", "reasons", "tradeoffs", "conditions", "limitations", "knowledge_ids")
    @classmethod
    def nonblank_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("构图方案字段不能包含空白条目。")
        return list(dict.fromkeys(value.strip() for value in values))

    @field_validator("crop_bbox", mode="before")
    @classmethod
    def numeric_box(cls, value: object) -> object:
        if value is not None and (
            not isinstance(value, list)
            or len(value) != 4
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
        ):
            raise ValueError("裁切框必须是四个数值组成的归一化坐标。")
        return value

    @field_validator("crop_bbox")
    @classmethod
    def normalized_box(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return value
        if any(not math.isfinite(item) or not 0 <= item <= 1 for item in value):
            raise ValueError("裁切框必须使用 0 到 1 的有限坐标。")
        if value[0] >= value[2] or value[1] >= value[3]:
            raise ValueError("裁切框不能倒置或没有面积。")
        return value

    @model_validator(mode="after")
    def crop_action(self) -> CompositionProposal:
        if self.crop_bbox is not None and self.action_type != "crop":
            raise ValueError("只有裁切方案可以包含裁切框。")
        return self


class CompositionAdvice(CompositionModel):
    status: Literal["grounded", "unverified", "unavailable", "demo"]
    observations: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    proposals: list[CompositionProposal] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
