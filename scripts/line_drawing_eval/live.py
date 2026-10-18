"""E2 live runner, gated by A's frozen version and E's cloud ledger.

Nothing in this module runs without ``--live``. Every upload reserves budget
before the POST, never retries automatically, and keeps a failed attempt in the
denominator.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .evidence import load_json, sha256_file, write_json
from .ledger import BudgetError, Ledger
from .preflight import verify

CASE_IDS = ("02", "06", "07", "08")


def load_cases(manifest_path: Path, wanted: list[str]) -> list[dict[str, Any]]:
    manifest = load_json(manifest_path)
    samples = {str(item.get("id")): item for item in manifest.get("samples") or []}
    unknown = sorted(set(wanted) - set(samples))
    if unknown:
        raise ValueError(f"unknown cases: {', '.join(unknown)}")
    cases = []
    for case_id in wanted:
        sample = samples[case_id]
        photos = [Path(item) for item in sample.get("photos") or []]
        if len(photos) != 1 or not photos[0].is_file():
            raise ValueError(f"case {case_id} needs exactly one existing photo")
        digest = sha256_file(photos[0])
        if digest != sample.get("sha256"):
            raise ValueError(f"case {case_id} photo hash differs from manifest")
        cases.append({**sample, "id": case_id, "photo": str(photos[0]), "sha256": digest})
    return cases


def summarize(
    final: dict[str, Any] | None,
    *,
    case_id: str,
    sample_sha256: str,
    seconds: float,
    events: list[dict[str, Any]],
    ready: dict[str, Any] | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "case_id": case_id,
        "success": False,
        "gateway_analysis_posts": 1,
        "outer_retries": 0,
        "sha256": sample_sha256,
        "seconds": round(seconds, 3),
        "first_events_seconds": _first_events(events),
        "internal_cloud_request_starts_by_stage": dict(
            Counter(
                event.get("stage")
                for event in events
                if event.get("type") == "activity" and event.get("phase") == "request_started"
            )
        ),
        "cache_events": [
            event
            for event in events
            if event.get("phase") in {"cache_hit", "cache_miss"}
            or "cache" in str(event.get("stage", ""))
        ],
    }
    row["internal_cloud_request_starts_total"] = sum(
        row["internal_cloud_request_starts_by_stage"].values()
    )
    row["observation_protocol_repairs"] = max(
        0, row["internal_cloud_request_starts_by_stage"].get("composition_observation", 0) - 1
    )
    if final is None:
        row["failure_code"] = "connection_ended_without_final"
        return row
    result = final.get("result") or {}
    composition = result.get("composition") or {}
    proposals = composition.get("proposals") or []
    boards = [
        proposal.get("storyboard")
        for proposal in proposals
        if isinstance(proposal, dict) and proposal.get("storyboard")
    ]
    row.update(
        {
            "success": bool(result.get("scene") and result.get("recommendation")),
            "proposal_count": len(proposals),
            "backend_board_count": len(boards),
            "timings": final.get("timings") or [],
            "diagnostics": [
                {
                    "stage": item.get("stage"),
                    "status": item.get("status"),
                    "code": item.get("code"),
                    "object_id": item.get("object_id"),
                    "field_path": item.get("field_path"),
                }
                for item in composition.get("diagnostics") or []
                if isinstance(item, dict)
            ],
            "knowledge_hit_count": len(result.get("composition_knowledge_hits") or []),
            "ready_matches_final": ready == composition if ready is not None else None,
        }
    )
    return row


def _first_events(events: list[dict[str, Any]]) -> dict[str, float]:
    first: dict[str, float] = {}
    for event in events:
        kind = event.get("kind") if event.get("type") == "partial" else event.get("type")
        if kind and kind not in first:
            first[str(kind)] = float(event.get("client_seconds") or 0.0)
    return first


def analyze_case(client: Any, case: dict[str, Any], target: Path) -> dict[str, Any]:
    """Send one complete analysis; no transport or analysis retries."""
    target.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    events: list[dict[str, Any]] = []
    final = None
    ready = None
    row: dict[str, Any] = {"case_id": case["id"], "gateway_analysis_posts": 0}
    try:
        health = client.get("/health")
        health.raise_for_status()
        write_json(target / "health.json", health.json())
        client.post("/session").raise_for_status()
        row["gateway_analysis_posts"] = 1
        with client.stream(
            "POST",
            "/api/v1/analyze",
            files={
                "file": (
                    "test-photo.jpg",
                    Path(case["photo"]).read_bytes(),
                    "image/jpeg",
                )
            },
            data={
                "consent": "true",
                "expected_analysis_mode": "cloud",
                "image_provenance": "original_upload",
                "stream_events": "true",
                "user_request": json.dumps(case["request"], ensure_ascii=False),
            },
        ) as response:
            row["http_status"] = response.status_code
            if response.status_code != 200:
                row["failure_code"] = "http_non_200"
            elif "application/x-ndjson" not in response.headers.get("content-type", ""):
                row["failure_code"] = "stream_content_type_invalid"
            else:
                for line in response.iter_lines():
                    if not line:
                        continue
                    event = json.loads(line)
                    now = round(time.monotonic() - started, 3)
                    kind = event.get("kind") if event.get("type") == "partial" else event.get("type")
                    safe = {
                        key: event[key]
                        for key in (
                            "type", "kind", "stage", "status", "duration_seconds",
                            "elapsed_seconds", "phase", "chars", "complete", "streamed",
                            "first_content_seconds", "error_category",
                        )
                        if key in event
                    }
                    events.append({**safe, "client_seconds": now})
                    if event.get("type") == "partial":
                        if kind == "composition_ready":
                            ready = event.get("value")
                            write_json(target / "ready.json", ready)
                    elif event.get("type") == "error":
                        row["failure_code"] = "analysis_error_event"
                        break
                    elif event.get("type") == "result":
                        final = {
                            key: value
                            for key, value in event.items()
                            if key not in {"type", "elapsed_seconds"}
                        }
        if final is not None:
            write_json(target / "result.json", final)
        summary = summarize(
            final,
            case_id=case["id"],
            sample_sha256=case["sha256"],
            seconds=time.monotonic() - started,
            events=events,
            ready=ready if isinstance(ready, dict) else None,
        )
        if "failure_code" in row:
            summary["failure_code"] = row["failure_code"]
        row.update(summary)
        if final is None:
            row.setdefault("failure_code", "connection_ended_without_final")
    except Exception as error:  # noqa: BLE001 - no raw message: it may hold private config
        row["failure_code"] = "client_or_parsing_failed"
        row["error_type"] = type(error).__name__
        row["seconds"] = round(time.monotonic() - started, 3)
        row.setdefault("gateway_analysis_posts", 0)
    finally:
        write_json(target / "events.json", events)
        write_json(target / "summary.json", row)
    return row


def _client(origin: str) -> Any:
    import httpx

    return httpx.Client(
        base_url=origin,
        headers={"Origin": origin, "X-Xiaoli-Client": "web"},
        timeout=httpx.Timeout(600, connect=15),
        trust_env=False,
        transport=httpx.HTTPTransport(retries=0),
    )


def run_batch(
    *,
    gate_path: Path,
    ledger_path: Path,
    manifest_path: Path,
    out_root: Path,
    run_name: str,
    case_ids: list[str],
    parallel: int = 1,
    client_factory: Callable[[str], Any] = _client,
) -> dict[str, Any]:
    if parallel != 1:
        raise ValueError("E2 runs sequentially so per-case wall time is comparable")
    if not run_name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("run_name must be simple ASCII")
    preflight = verify(gate_path, ledger_path, explicit_live=True)
    ledger = Ledger.load(ledger_path)
    cases = load_cases(manifest_path, case_ids)
    if len(cases) > ledger.remaining:
        raise BudgetError(
            f"{len(cases)} uploads requested but only {ledger.remaining} gateway posts remain"
        )
    run_dir = out_root / run_name
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    write_json(run_dir / "preflight.json", preflight)
    write_json(
        run_dir / "run_manifest.json",
        {
            "kind": "e2_live_acceptance",
            "created_at": _now(),
            "gate": preflight["gate"],
            "origin": preflight["origin"],
            "source_fingerprint": preflight["source_fingerprint"],
            "health": preflight["health"],
            "parallel": parallel,
            "cases": [
                {key: case.get(key) for key in ("id", "title", "photo", "sha256", "request", "intent")}
                for case in cases
            ],
            "gateway_budget": {
                "total": ledger.data["budget"]["total_gateway_posts"],
                "used_before": ledger.data["budget"]["used_gateway_posts"],
                "remaining_before": ledger.remaining,
            },
        },
    )
    rows = []
    client = client_factory(preflight["origin"])
    try:
        for case in cases:
            reservation = ledger.reserve(case["id"], f"E2 acceptance {run_name}")
            ledger.save()
            row = analyze_case(client, case, run_dir / case["id"])
            ledger.finalize(
                reservation,
                outcome="complete" if row.get("success") else "failed",
                seconds=row.get("seconds"),
                internal_request_starts=row.get("internal_cloud_request_starts_total"),
                protocol_repairs=row.get("observation_protocol_repairs"),
                evidence=str(run_dir / case["id"]),
            )
            ledger.save()
            rows.append(row)
            write_json(
                run_dir / "live_results.json",
                {
                    "kind": "e2_live_acceptance",
                    "runs": rows,
                    "total": len(rows),
                    "planned": len(cases),
                    "gateway_analysis_posts": sum(
                        int(item.get("gateway_analysis_posts") or 0) for item in rows
                    ),
                    "successes": sum(bool(item.get("success")) for item in rows),
                    "outer_retries": 0,
                },
            )
    finally:
        client.close()
    return {
        "run_dir": str(run_dir),
        "rows": rows,
        "remaining_gateway_posts": ledger.remaining,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--cases", default="06,07,02")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    wanted = [item for item in args.cases.split(",") if item]
    if not args.live:
        # Read-only verification still needs the gate file; it never POSTs.
        report = verify(args.gate, args.ledger, explicit_live=False)
        ledger = Ledger.load(args.ledger)
        cases = load_cases(args.manifest, wanted)
        plan = {
            "preflight": report,
            "cases": [case["id"] for case in cases],
            "remaining_gateway_posts": ledger.remaining,
            "can_run": len(cases) <= ledger.remaining,
            "dry_run": True,
            "generated_model_requests": 0,
            "health_get_requests": report["health_get_requests"],
        }
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0 if plan["can_run"] else 1
    if args.dry_run:
        raise SystemExit("--dry-run and --live are mutually exclusive")
    result = run_batch(
        gate_path=args.gate,
        ledger_path=args.ledger,
        manifest_path=args.manifest,
        out_root=args.out,
        run_name=args.run_name,
        case_ids=wanted,
    )
    print(json.dumps({key: value for key, value in result.items() if key != "rows"},
                     ensure_ascii=False, indent=2))
    return 0


def _now() -> str:
    import datetime as _dt

    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
