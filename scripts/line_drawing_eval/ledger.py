"""E-owned cloud budget ledger and live-run gate.

Every gateway POST is counted, including failures. A reservation is written
before any request would be sent, so a crash or a failed attempt can never
silently restore budget. E1 ships no code path that performs a model request.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import SCHEMA_LEDGER
from .evidence import load_json, write_json


class BudgetError(RuntimeError):
    """Raised when a live action would exceed the handed-over budget."""


class GateError(RuntimeError):
    """Raised when the integrated version has not been frozen by A."""


@dataclass
class Ledger:
    path: Path
    data: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> Ledger:
        data = load_json(path)
        if data.get("schema") != SCHEMA_LEDGER:
            raise ValueError(f"unexpected ledger schema in {path}")
        ledger = cls(path=path, data=data)
        ledger.validate()
        return ledger

    @classmethod
    def create_inherited(
        cls,
        path: Path,
        handoff: dict[str, Any],
        *,
        total_budget: int = 8,
        used: int = 5,
        internal_starts: int = 22,
        protocol_repairs: int = 2,
        outer_retries: int = 0,
    ) -> Ledger:
        now = _utc_now()
        data = {
            "schema": SCHEMA_LEDGER,
            "owner": "E",
            "created_at": now,
            "budget": {
                "total_gateway_posts": total_budget,
                "used_gateway_posts": used,
                "remaining_gateway_posts": total_budget - used,
            },
            "internal_request_starts": {"used": internal_starts},
            "observation_protocol_repairs": {"used": protocol_repairs},
            "outer_retries": {"used": outer_retries},
            "inherited_from": "reports/A-cloud-handoff.json",
            "inherited_attempts": handoff.get("attempts") or [],
            "reservations": [],
            "history": [
                {
                    "at": now,
                    "event": "created_from_A_handoff",
                    "note": (
                        "Inherited 5/8 full gateway posts, 22 internal request_started events, "
                        "2 observation protocol repairs and 0 outer retries. This is not a new "
                        "allowance of 8."
                    ),
                }
            ],
            "policy": {
                "default_mode": "offline_replay",
                "live_requires_explicit_flag": True,
                "live_requires_integration_ready": True,
                "auto_retry": False,
                "failed_attempt_still_counts": True,
                "owner_after_handoff": "E",
            },
        }
        ledger = cls(path=path, data=data)
        ledger.validate()
        return ledger

    def validate(self) -> None:
        budget = self.data["budget"]
        total = int(budget["total_gateway_posts"])
        used = int(budget["used_gateway_posts"])
        remaining = int(budget["remaining_gateway_posts"])
        if total < 0 or used < 0:
            raise ValueError("negative budget values")
        if used > total:
            raise ValueError("used gateway posts exceed total budget")
        if remaining != total - used:
            raise ValueError(
                f"remaining={remaining} does not match total-used={total - used}; "
                "fix the ledger instead of assuming budget"
            )

    @property
    def remaining(self) -> int:
        return int(self.data["budget"]["remaining_gateway_posts"])

    def save(self) -> None:
        self.validate()
        write_json(self.path, self.data)

    def reserve(self, case_id: str, reason: str) -> str:
        if self.remaining <= 0:
            raise BudgetError("no gateway posts remain; do not retry or reallocate silently")
        reservation_id = _dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
        budget = self.data["budget"]
        budget["used_gateway_posts"] += 1
        budget["remaining_gateway_posts"] -= 1
        self.data["reservations"].append(
            {
                "id": reservation_id,
                "case_id": case_id,
                "reason": reason,
                "reserved_at": _utc_now(),
                "status": "reserved",
                "gateway_posts": 1,
            }
        )
        self.validate()
        return reservation_id

    def finalize(
        self,
        reservation_id: str,
        *,
        outcome: str,
        seconds: float | None = None,
        internal_request_starts: int | None = None,
        protocol_repairs: int | None = None,
        evidence: str | None = None,
    ) -> None:
        for item in self.data["reservations"]:
            if item.get("id") != reservation_id:
                continue
            item.update(
                {
                    "status": outcome,
                    "finished_at": _utc_now(),
                    "seconds": seconds,
                    "internal_request_starts": internal_request_starts,
                    "observation_protocol_repairs": protocol_repairs,
                    "evidence": evidence,
                }
            )
            if internal_request_starts:
                self.data["internal_request_starts"]["used"] += int(internal_request_starts)
            if protocol_repairs:
                self.data["observation_protocol_repairs"]["used"] += int(protocol_repairs)
            return
        raise KeyError(f"unknown reservation {reservation_id}")

    def require_live_allowed(self, *, explicit_live: bool, integration_gate: Path) -> None:
        if not explicit_live:
            raise GateError("offline/read-only mode is the default; pass --live to opt in")
        if not integration_gate.is_file():
            raise GateError(
                f"missing INTEGRATION_READY gate {integration_gate}; do not test an unverified version"
            )
        gate = load_json(integration_gate)
        required = {"status", "commit", "port", "pid", "built_assets", "frozen_at"}
        missing = sorted(required - set(gate))
        if missing:
            raise GateError(f"integration gate missing fields: {', '.join(missing)}")
        if gate.get("status") != "INTEGRATION_READY":
            raise GateError("integration gate status is not INTEGRATION_READY")
        if self.remaining <= 0:
            raise BudgetError("ledger has no remaining gateway posts")


def _utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
