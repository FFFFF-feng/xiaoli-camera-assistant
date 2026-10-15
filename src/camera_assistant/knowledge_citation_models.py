"""Model proposals and program audit are distinct; neither is a human source review."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_path: str = Field(min_length=1, max_length=200)
    claim: str = Field(min_length=4, max_length=1500)
    document_id: str = Field(min_length=1, max_length=500)
    version: int = Field(ge=1, strict=True)
    source_excerpt: str = Field(min_length=4, max_length=1500)


class ReviewedKnowledgeCitation(BaseModel):
    citation: KnowledgeCitation | None = None
    reason: str
    title: str = ""
    source: str = ""
    source_url: str = ""
    source_license: str = ""
    conditions: dict = Field(default_factory=dict)
    applicability_requires: list[str] = Field(default_factory=list)
    usage_scope: str = "unknown"
    support_scope: Literal["quoted_general_principle", "unsupported"] = "unsupported"


class KnowledgeCitationReview(BaseModel):
    accepted: list[ReviewedKnowledgeCitation] = Field(default_factory=list)
    rejected: list[ReviewedKnowledgeCitation] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
