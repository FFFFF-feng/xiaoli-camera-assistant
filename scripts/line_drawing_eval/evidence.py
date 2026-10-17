"""Index stored analysis runs without inventing missing values."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import SCHEMA_RUN


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


@dataclass(frozen=True)
class RunLayout:
    """Files that make up one stored attempt directory."""

    root: Path
    run: str
    case_id: str

    @property
    def summary_path(self) -> Path:
        return self.root / "summary.json"

    @property
    def events_path(self) -> Path:
        return self.root / "events.json"

    @property
    def result_path(self) -> Path:
        return self.root / "result.json"

    def optional(self, name: str) -> Path | None:
        path = self.root / name
        return path if path.is_file() else None


def discover_runs(evidence_root: Path) -> list[RunLayout]:
    """Find ``<run>/<case>/summary.json`` directories below ``evidence_root``.

    The evidence tree also contains non-run helper summaries (for example mask
    experiments). Only a summary carrying a case id and stage timings is a
    complete analysis attempt.
    """
    layouts: list[RunLayout] = []
    for summary in sorted(evidence_root.glob("*/*/summary.json")):
        try:
            payload = load_json(summary)
        except (OSError, ValueError):
            continue
        if not (
            isinstance(payload, dict)
            and payload.get("case_id")
            and isinstance(payload.get("timings"), list)
        ):
            continue
        case_dir = summary.parent
        layouts.append(RunLayout(root=case_dir, run=case_dir.parent.name, case_id=case_dir.name))
    return layouts


def _manifest_sample(manifest: dict[str, Any] | None, case_id: str) -> dict[str, Any] | None:
    if not isinstance(manifest, dict):
        return None
    for sample in manifest.get("samples") or []:
        if str(sample.get("id")) == case_id:
            return sample
    return None


def _diagnostic_codes(summary: dict[str, Any]) -> list[dict[str, Any]]:
    codes = []
    for item in summary.get("diagnostics") or []:
        if not isinstance(item, dict):
            continue
        status = item.get("status")
        if status in {"failed", "error"}:
            codes.append(
                {
                    "stage": item.get("stage"),
                    "code": item.get("code"),
                    "status": status,
                    "object_id": item.get("object_id"),
                    "field_path": item.get("field_path"),
                }
            )
    return codes


def _board_counts(result: dict[str, Any] | None) -> dict[str, Any]:
    counts = {"proposals": 0, "boards": 0, "layers": 0}
    if not isinstance(result, dict):
        return counts
    composition = (result.get("result") or {}).get("composition") or {}
    proposals = composition.get("proposals") or []
    if not isinstance(proposals, list):
        return counts
    counts["proposals"] = len(proposals)
    for proposal in proposals:
        board = proposal.get("storyboard") if isinstance(proposal, dict) else None
        layers = board.get("layers") if isinstance(board, dict) else None
        if isinstance(layers, list):
            counts["boards"] += 1
            counts["layers"] += len(layers)
    return counts


def index_run(layout: RunLayout) -> dict[str, Any]:
    """Build a self-describing record for one stored attempt.

    Missing facts stay explicitly unknown. In particular this function never
    claims a model name, a clean tree, or a raw mask that the evidence does not
    contain.
    """
    summary = load_json(layout.summary_path)
    if not isinstance(summary, dict):
        raise TypeError(f"summary is not an object: {layout.summary_path}")
    events = load_json(layout.events_path) if layout.events_path.is_file() else []
    result = load_json(layout.result_path) if layout.result_path.is_file() else None
    manifest_path = layout.root.parent / "run_manifest.json"
    manifest = load_json(manifest_path) if manifest_path.is_file() else None
    sample = _manifest_sample(manifest, layout.case_id)

    original = None
    if sample and isinstance(sample.get("photos"), list) and sample["photos"]:
        photo_path = Path(sample["photos"][0])
        recorded = sample.get("sha256")
        actual = sha256_file(photo_path) if photo_path.is_file() else None
        original = {
            "path": str(photo_path),
            "exists": photo_path.is_file(),
            "sha256_recorded": recorded,
            "sha256_observed": actual,
            "sha256_matches": bool(recorded and actual and recorded == actual),
        }

    fingerprint = summary.get("source_fingerprint")
    manifest_fingerprint = (manifest or {}).get("source_fingerprint") or {}
    return {
        "schema": SCHEMA_RUN,
        "kind": "stored_result_replay",
        "offline": True,
        "generated_model_requests": 0,
        "run": layout.run,
        "case_id": layout.case_id,
        "evidence_dir": str(layout.root),
        "source": {
            "git_sha": summary.get("git_sha") or (manifest or {}).get("git_sha"),
            "source_fingerprint": fingerprint,
            "tracked_diff_sha256": manifest_fingerprint.get("tracked_diff_sha256"),
            "dirty": "unrecorded_by_run_manifest",
            "note": (
                "Produced before checkpoint 986fd059; treated as localization evidence only, "
                "not as acceptance evidence for an integrated version."
            ),
        },
        "analysis_mode": summary.get("analysis_mode"),
        "device": {
            "backend": "cloud",
            "model": "unrecorded_in_run_manifest",
            "note": (
                "The run summary records call counts and stage timings but not provider model ids. "
                "Do not infer a model version from the current default configuration."
            ),
        },
        "configuration": {
            **(manifest or {}).get("configuration", {}),
            "gateway_budget": (manifest or {}).get("gateway_budget"),
        },
        "original": original,
        "request": (sample or {}).get("request"),
        "intent": (sample or {}).get("intent"),
        "attempts": [
            {
                "index": 1,
                "kind": "full_analysis_gateway_post",
                "gateway_posts": summary.get("gateway_analysis_posts"),
                "seconds": summary.get("seconds"),
                "http_status": summary.get("http_status"),
                "success": summary.get("success"),
                "valid_board": bool(summary.get("backend_board_count")),
                "trace_id": summary.get("trace_id"),
                "internal_request_starts": summary.get("internal_cloud_request_starts_total"),
                "observation_protocol_repairs": summary.get("observation_protocol_repairs"),
                "outer_retries": summary.get("outer_retries"),
            }
        ],
        "failure_codes": _diagnostic_codes(summary),
        "artifacts": {
            key: str(path)
            for key, path in {
                "events": layout.optional("events.json"),
                "result": layout.optional("result.json"),
                "ready": layout.optional("ready.json"),
                "observation_replay": layout.optional("observation-replay.json"),
                "health": layout.optional("health.json"),
            }.items()
            if path is not None
        },
        "artifact_sha256": {
            name: sha256_file(Path(path))
            for name, path in {
                "summary": layout.summary_path,
                "events": layout.optional("events.json"),
                "result": layout.optional("result.json"),
            }.items()
            if path is not None
        },
        "timings": summary.get("timings") or [],
        "first_events_seconds": summary.get("first_events_seconds") or {},
        "internal_cloud_request_starts_by_stage": summary.get(
            "internal_cloud_request_starts_by_stage"
        ),
        "boards": _board_counts(result),
        "masks": {
            "raw_mask_saved": False,
            "note": (
                "No raw boolean mask image is stored in this run. Only the traced geometry "
                "(outline/contours/holes) survives in result.json, so mask quality cannot be "
                "re-derived from these files alone."
            ),
        },
        "event_count": len(events) if isinstance(events, list) else 0,
    }


def index_root(evidence_root: Path) -> dict[str, Any]:
    runs = [index_run(layout) for layout in discover_runs(evidence_root)]
    runs.sort(key=lambda item: (str(item["run"]), str(item["case_id"])))
    return {
        "schema": "line-drawing-eval-index-v1",
        "kind": "stored_result_replay",
        "offline": True,
        "generated_model_requests": 0,
        "root": str(evidence_root),
        "run_count": len(runs),
        "gateway_posts_represented": sum(
            int((run.get("attempts") or [{}])[0].get("gateway_posts") or 0) for run in runs
        ),
        "runs": runs,
    }
