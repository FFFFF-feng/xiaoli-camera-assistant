"""Reconstruct the real critical path from recorded stage and stream events.

Stage durations come from the server's monotonic measurements. Stream events
only explain where a cloud call spends its time; they are not added to stage
durations. Parallel branches are combined with max(), never summed.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .evidence import RunLayout, load_json

CLOUD_STAGES = ("vision", "parameters", "composition_observation", "composition_layout")


def _activity_calls(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group stream activity into one record per request_started event."""
    calls: list[dict[str, Any]] = []
    open_by_stage: dict[str, dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "activity":
            continue
        stage = str(event.get("stage"))
        phase = event.get("phase")
        if phase == "request_started":
            call = {
                "stage": stage,
                "sequence": len(calls) + 1,
                "started_seconds": float(event.get("client_seconds") or 0.0),
                "content": [],
                "finished_seconds": None,
                "complete": None,
                "streamed": None,
            }
            calls.append(call)
            open_by_stage[stage] = call
            continue
        call = open_by_stage.get(stage)
        if call is None:
            continue
        if phase == "content":
            call["content"].append(
                (float(event.get("client_seconds") or 0.0), int(event.get("chars") or 0))
            )
        elif phase == "finished":
            call["finished_seconds"] = float(event.get("client_seconds") or 0.0)
            call["complete"] = event.get("complete")
            call["streamed"] = event.get("streamed")

    for call in calls:
        content = call["content"]
        if content:
            call["first_content_seconds"] = content[0][0] - call["started_seconds"]
            call["last_content_seconds"] = content[-1][0] - call["started_seconds"]
            call["generation_seconds"] = content[-1][0] - content[0][0]
            call["chars"] = int(content[-1][1])
        else:
            call["first_content_seconds"] = None
            call["last_content_seconds"] = None
            call["generation_seconds"] = None
            call["chars"] = 0
        if call["finished_seconds"] is not None:
            call["call_seconds"] = call["finished_seconds"] - call["started_seconds"]
            tail_from = content[-1][0] if content else call["finished_seconds"]
            call["tail_seconds"] = max(0.0, call["finished_seconds"] - tail_from)
        else:
            call["call_seconds"] = None
            call["tail_seconds"] = None
        call.pop("content", None)
    return calls


def _stage_totals(timings: Iterable[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for item in timings:
        if not isinstance(item, dict):
            continue
        stage = str(item.get("stage"))
        totals[stage] = totals.get(stage, 0.0) + float(item.get("duration_seconds") or 0.0)
    return totals


def analyze_run(run_dir: Path, *, run: str = "", case_id: str = "") -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(summary_path)
    summary = load_json(summary_path)
    events_path = run_dir / "events.json"
    events = load_json(events_path) if events_path.is_file() else []
    totals = _stage_totals(summary.get("timings") or [])
    calls = _activity_calls(events if isinstance(events, list) else [])

    vision = totals.get("vision")
    parameters = totals.get("parameters")
    composition = totals.get("composition")
    preprocessing = totals.get("image_preprocessing", 0.0)
    measured_total = totals.get("total")
    if None in (vision, parameters, composition, measured_total):
        raise ValueError(f"missing required stage timings in {summary_path}")
    predicted_total = preprocessing + vision + max(parameters, composition)
    residual = measured_total - predicted_total
    critical_branch = "composition" if composition > parameters else "parameters"
    branch_gap = abs(parameters - composition)

    first = summary.get("first_events_seconds") or {}
    ready_lead = None
    if isinstance(first.get("result"), (int, float)) and isinstance(
        first.get("composition_ready"), (int, float)
    ):
        ready_lead = float(first["result"]) - float(first["composition_ready"])

    wall = float(summary.get("seconds") or measured_total)
    segments = [
        {"stage": "image_preprocessing", "seconds": preprocessing, "on_critical_path": True},
        {"stage": "vision", "seconds": vision, "on_critical_path": True},
        {
            "stage": "parameters",
            "seconds": parameters,
            "on_critical_path": critical_branch == "parameters",
        },
        {
            "stage": "composition",
            "seconds": composition,
            "on_critical_path": critical_branch == "composition",
        },
    ]
    ranked = sorted(segments, key=lambda item: item["seconds"], reverse=True)

    cloud_calls = []
    for call in calls:
        if call["stage"] not in CLOUD_STAGES:
            continue
        cloud_calls.append(
            {
                "stage": call["stage"],
                "sequence": call["sequence"],
                "started_seconds": round(call["started_seconds"], 3),
                "call_seconds": _round(call["call_seconds"]),
                "time_to_first_content_seconds": _round(call["first_content_seconds"]),
                "generation_seconds": _round(call["generation_seconds"]),
                "tail_seconds": _round(call["tail_seconds"]),
                "content_chars": call["chars"],
                "complete": call["complete"],
                "streamed": call["streamed"],
            }
        )

    return {
        "run": run or run_dir.parent.name,
        "case_id": case_id or run_dir.name,
        "success": summary.get("success"),
        "wall_seconds": round(wall, 3),
        "measured_total_seconds": round(measured_total, 3),
        "predicted_total_seconds": round(predicted_total, 3),
        "residual_seconds": round(residual, 3),
        "critical_branch": critical_branch,
        "branch_gap_seconds": round(branch_gap, 3),
        "segments": [
            {**item, "seconds": round(item["seconds"], 3)} for item in segments
        ],
        "ranked_segments": [
            {**item, "seconds": round(item["seconds"], 3)} for item in ranked
        ],
        "cloud_calls": cloud_calls,
        "ready_lead_seconds": _round(ready_lead),
        "ready_matches_final": summary.get("ready_matches_final"),
        "internal_request_starts": summary.get("internal_cloud_request_starts_total"),
        "observation_protocol_repairs": summary.get("observation_protocol_repairs"),
        "failure_codes": [
            item.get("code")
            for item in summary.get("diagnostics") or []
            if isinstance(item, dict) and item.get("status") == "failed"
        ],
        "formula": (
            "image_preprocessing + vision + max(parameters, composition); "
            "parallel intervals are never added together"
        ),
    }


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not runs:
        return {"run_count": 0}
    stage_totals: dict[str, float] = {}
    for run in runs:
        for segment in run["segments"]:
            stage_totals[segment["stage"]] = stage_totals.get(segment["stage"], 0.0) + segment[
                "seconds"
            ]
    total = sum(run["wall_seconds"] for run in runs)
    stage_share = {
        stage: {
            "total_seconds": round(seconds, 3),
            "share_of_summed_wall_seconds": round(seconds / total, 4) if total else None,
            "mean_seconds": round(seconds / len(runs), 3),
            "median_seconds": round(
                statistics.median(
                    [segment["seconds"] for run in runs for segment in run["segments"]
                     if segment["stage"] == stage]
                ),
                3,
            ),
        }
        for stage, seconds in sorted(stage_totals.items(), key=lambda item: item[1], reverse=True)
    }
    cloud: dict[str, dict[str, Any]] = {}
    for run in runs:
        for call in run["cloud_calls"]:
            bucket = cloud.setdefault(
                call["stage"],
                {"calls": 0, "call_seconds": 0.0, "ttft_seconds": 0.0, "generation_seconds": 0.0},
            )
            bucket["calls"] += 1
            bucket["call_seconds"] += call["call_seconds"] or 0.0
            bucket["ttft_seconds"] += call["time_to_first_content_seconds"] or 0.0
            bucket["generation_seconds"] += call["generation_seconds"] or 0.0
    cloud_summary = {
        stage: {
            "calls": bucket["calls"],
            "mean_call_seconds": round(bucket["call_seconds"] / bucket["calls"], 3),
            "mean_time_to_first_content_seconds": round(
                bucket["ttft_seconds"] / bucket["calls"], 3
            ),
            "mean_generation_seconds": round(bucket["generation_seconds"] / bucket["calls"], 3),
            "ttft_share_of_call": round(
                bucket["ttft_seconds"] / bucket["call_seconds"], 4
            )
            if bucket["call_seconds"]
            else None,
        }
        for stage, bucket in cloud.items()
    }
    return {
        "run_count": len(runs),
        "summed_wall_seconds": round(total, 3),
        "critical_branch_counts": {
            branch: sum(1 for run in runs if run["critical_branch"] == branch)
            for branch in ("parameters", "composition")
        },
        "stage_totals": stage_share,
        "cloud_call_summary": cloud_summary,
        "runs": runs,
    }


def analyze_layouts(layouts: list[RunLayout]) -> dict[str, Any]:
    return aggregate([analyze_run(layout.root, run=layout.run, case_id=layout.case_id) for layout in layouts])


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 3)
