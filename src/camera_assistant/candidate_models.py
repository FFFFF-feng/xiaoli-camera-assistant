"""Model claims are candidates, never evidence of their own correctness."""
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


class TrialAction(BaseModel):
    """Program interpretation of an explicit model action, without its claimed effect."""

    kind: Literal["lateral_translation", "depth_translation", "height_translation",
                  "pitch", "rotation", "subject_pose", "light_position", "focus"]
    target: Literal["camera", "subject", "light", "focus"]
    direction: str
    condition: str = ""
    source_text: str
    source: Literal["model_action"] = "model_action"


class FieldCheck(BaseModel):
    """A program-supplied field test, not a measured or model-certified result."""

    issue: str
    observe: str
    accept_when: str
    protect: str
    basis: str
    source: Literal["program"] = "program"


class FactReference(BaseModel):
    # Unsupported provenance is rejected during review, not as a fatal error
    # for the independent, otherwise usable recommendation.
    source: str
    key: str
    evidence: str


class CandidateOperation(BaseModel):
    control: str
    target: str
    expected_effect: str
    preconditions: list[FactReference] = Field(default_factory=list)
    object_ids: list[str] = Field(default_factory=list)


def candidate_list(value: object) -> list[CandidateOperation]:
    """Isolate malformed optional metadata, retaining an explicit rejected claim."""
    result = []
    for item in value if isinstance(value, list) else [value]:
        try:
            result.append(CandidateOperation.model_validate(item))
        except (ValidationError, TypeError, ValueError):
            result.append(CandidateOperation(
                control="unparsed", target="unknown", expected_effect="unverified",
                preconditions=[FactReference(source="unknown", key="candidate_metadata",
                                             evidence="候选操作元数据结构无效，未审核")],
            ))
    return result
