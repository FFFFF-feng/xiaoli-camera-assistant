"""Program-owned parameter completeness and bounded recovery diagnostics."""
from typing import Literal

from pydantic import BaseModel, Field


class ParameterRecovery(BaseModel):
    status: Literal["complete", "needs_confirmation", "incomplete"] = "incomplete"
    missing_parameters: list[str] = Field(default_factory=list)
    fact_parameters: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    user_confirmations: list[str] = Field(default_factory=list)
    correction_attempted: bool = False
    api_calls: int = 0
    call_limit: int = 2
    format_failures: int = 0
