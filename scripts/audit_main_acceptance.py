"""Summarize recorded evidence only; never sends an API request or changes old results."""
from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "data/history/main-acceptance-20261014"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    live = EVIDENCE / "live"
    trials, calls = [], []
    for path in sorted(live.glob("*-summary.json")):
        data = read(path)
        trials.append(data)
        calls.extend({**c, "case": data["case"]} for c in data["calls"])
    rows = []
    for data in trials:
        case = data["case"]
        ui_path = EVIDENCE / f"ui/{case}-result.json"
        ui = read(ui_path) if ui_path.exists() else {}
        final_path = live / f"{case}-pipeline.json"
        final = read(final_path) if final_path.exists() else None
        rows.append({
            "case": case, "returned": data["returned"],
            "stage_seconds": data["stage_seconds"],
            "first_raw_seconds": data["milestones"].get("first_raw_model_result_seconds"),
            "first_composition_ready_seconds": data["milestones"].get("first_composition_result_seconds"),
            "pipeline_complete_seconds": data["complete_result_seconds"],
            "actual_browser_result_observed_seconds": ui.get("elapsed_seconds"),
            "calls": data["real_model_calls"], "corrections": data["parameter_correction_calls"],
            "parameter_recovery": data.get("parameter_recovery"),
            "visual_and_detector_and_composition_runs": {k: len(data["stages"].get(k, []))
                                                         for k in ("vision", "detector", "composition")},
            "ui": {k: ui.get(k) for k in ("upload_verified", "result_verified",
                    "environment_position_visible", "environment_uncertainty_visible", "no_exception_overlay")},
            "final_settings": {k: final["recommendation"][k] for k in (
                "shooting_mode", "aperture", "shutter_speed", "iso", "exposure_compensation")}
                if final else None,
            "scene_environment": final["scene"]["environment_context"] if final else None,
            "localization_selection": final["localization"]["selection"]["status"]
                if final and final["localization"] else None,
            "composition_proposals": len(final["composition"]["proposals"])
                if final and final["composition"] else 0,
            "knowledge_hits": [h["document_id"] for h in final["knowledge_hits"]] if final else [],
        })
    post = read(live / "postflight.json") if (live / "postflight.json").exists() else {}
    pre = read(live / "preflight.json") if (live / "preflight.json").exists() else {}
    comp = EVIDENCE / "knowledge-comparison"
    compare = read(comp / "summary.json") if (comp / "summary.json").exists() else {"trials": []}
    comparison_calls = [c for trial in compare["trials"] for c in trial["calls"]]
    all_calls = [*calls, *comparison_calls]
    result = {
        "completed_full_flows": len(trials), "expected_full_flows": 6,
        "full_flow_calls": len(calls), "knowledge_comparison_calls": len(comparison_calls),
        "real_api_calls_total": len(all_calls),
        "parameter_correction_requests_total": sum(c["purpose"] == "parameter_correction" for c in all_calls),
        "format_issues_total": sum(c.get("json_valid") is False for c in all_calls),
        "connection_failures": sum(c.get("error_category") == "connection" for c in all_calls),
        "timeouts": sum(c.get("error_category") == "timeout" for c in all_calls),
        "http_failures": sum(c.get("error_category") == "http_status" for c in all_calls),
        "refusals_or_truncation": [c for c in all_calls if c.get("error_category") in {"refusal", "truncated"}],
        "full_flow_complete_seconds_sum": round(sum(t["complete_result_seconds"] for t in trials), 3),
        "full_flow_complete_seconds_median": statistics.median(t["complete_result_seconds"] for t in trials) if trials else None,
        "full_flow_complete_seconds_max": max((t["complete_result_seconds"] for t in trials), default=None),
        "stage_seconds_sum": {k: round(sum(t["stage_seconds"].get(k, 0) for t in trials), 3)
                              for k in ("vision", "detector", "composition", "parameters")},
        "production_code_hashes_match_preflight": pre.get("code") == post.get("code"),
        "production_database_logically_unchanged": post.get("source_database_logically_unchanged"),
        "trials": rows,
        "model_transport_and_review_are_separate": True,
        "human_photographic_accuracy_measurement": False,
        "harness_sha256": {name: hashlib.sha256((ROOT / "scripts" / name).read_bytes()).hexdigest()
                           for name in (
                               "main_round_support.py", "run_main_acceptance.py",
                               "run_acceptance_website.py", "check_main_website.cjs",
                               "compare_main_knowledge.py", "audit_main_acceptance.py",
                           )},
        "evidence_timing_note": "Original recorder website times are pipeline-return proxies; actual browser observation is saved separately in UI records. CLI comparison website time is null.",
        "incomplete_review_results": [r["case"] for r in rows
                                      if (r.get("parameter_recovery") or {}).get("status") == "incomplete"],
        "full_flow_initial_parameter_review_failures": sum(
            bool((t.get("parameter_recovery") or {}).get("correction_attempted")) for t in trials),
        "full_flow_terminal_parameter_review_failures": [
            t["case"] for t in trials
            if (t.get("parameter_recovery") or {}).get("status") == "incomplete"
            and not any(c.get("error_category") in {"timeout", "connection", "http_status"}
                        for c in t["calls"])
        ],
    }
    write(EVIDENCE / "acceptance-audit.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in {"trials", "harness_sha256"}},
                     ensure_ascii=True))


if __name__ == "__main__":
    main()
