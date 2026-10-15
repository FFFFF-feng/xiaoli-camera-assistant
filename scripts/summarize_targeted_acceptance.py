"""Audit new evidence without rewriting raw answers, old records or application state."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from main_round_support import code_snapshot, database_contents, read_json, write_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/history/main-targeted-20261015"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def all_text(body):
    chunks = []
    for message in body.get("messages", []):
        content = message.get("content", "")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            chunks.extend(part.get("text", "") for part in content if part.get("type") == "text")
    return "\n".join(chunks)


def main():
    from camera_assistant.models import KnowledgeHit
    from camera_assistant.services.knowledge_citations import knowledge_evidence_text

    runs = []
    for calls_path in sorted(OUT.rglob("*-calls.json")):
        calls = read_json(calls_path)
        if not calls or not isinstance(calls, list) or not isinstance(calls[0], dict) or "stage" not in calls[0]:
            continue
        folder = calls_path.parent
        case = calls_path.name.removesuffix("-calls.json")
        summary_path = folder / f"{case}-summary.json"
        if not summary_path.exists():
            continue
        summary = read_json(summary_path)
        final_path = folder / f"{case}-pipeline.json"
        final = read_json(final_path) if final_path.exists() else None
        retrievals = read_json(folder / f"{case}-retrieval.json")
        detailed_calls = []
        for call in calls:
            prefix = f"{case}-{call['stage']}-attempt{call['attempt']}"
            metadata_path = folder / f"{prefix}-response-metadata.json"
            metadata = read_json(metadata_path) if metadata_path.exists() else {}
            request = read_json(folder / f"{prefix}-request.json")
            text = all_text(request)
            hits = [hit for record in retrievals for hit in record["hits"] if (
                (call["stage"] == "composition") == ("composition" in record["arguments"].get("libraries", [])))] if call["stage"] != "vision" else []
            evidence = knowledge_evidence_text([KnowledgeHit.model_validate(hit) for hit in hits])
            source_items = json.loads(evidence)
            actual = (evidence in text if call["stage"] == "parameters" else
                      json.dumps(source_items, ensure_ascii=False) in text if call["stage"] == "composition" else None)
            detailed_calls.append({**call, "metadata": metadata,
                "request_text_chars": len(text),
                "retrieval_candidate_content_chars": sum(len(hit["content"]) for hit in hits),
                "injected_knowledge_json_chars": len(evidence) if call["stage"] != "vision" else 0,
                "injected_evidence_exactly_present": actual,
                "injected_document_ids": [item["document_id"] for item in source_items],
                "source_identity_fields_present": all(all(key in item for key in (
                    "document_id", "version", "title", "body", "source", "conditions")) for item in source_items),
            })
        runs.append({"case": case, "directory": str(folder.relative_to(OUT)),
            "execution": summary.get("execution", "8501 actual upload/form full flow"),
            "returned": summary["returned"], "calls": detailed_calls,
            "stage_seconds": summary["stage_seconds"],
            "pipeline_return_seconds": summary["complete_result_seconds"],
            "page_result_seconds": read_json(OUT / f"ui/{case}-result.json")["elapsed_seconds"]
                if folder.name == "live" and (OUT / f"ui/{case}-result.json").exists() else None,
            "recovery": summary["parameter_recovery"],
            "reused_scene": summary.get("scene_exactly_reused"),
            "reused_dino": summary.get("dino_exactly_reused"),
            "reused_inspection": summary.get("inspection_exactly_reused"),
            "parameters": {name: final["recommendation"][name] for name in (
                "shooting_mode", "aperture", "shutter_speed", "iso", "exposure_compensation")}
                if final else None,
            "citation_review": final.get("knowledge_citation_review") if final else None,
            "composition": [{"goal": p["goal"], "actions": p["actions"],
                "source_actions": p.get("action_evidence", []), "trial_actions": p.get("trial_actions", []),
                "field_checks": p.get("field_checks", []),
                "citation_review": p.get("knowledge_citation_review")}
                for p in (final.get("composition") or {}).get("proposals", [])] if final else [],
        })
    state = read_json(OUT / "start-state.json")
    unchanged = lambda key: {name: (ROOT / name).exists() and sha(ROOT / name) == value
                             for name, value in state[key].items()}
    old_unchanged, frozen_unchanged = unchanged("old_evidence_sha256"), unchanged("frozen_experiment_sha256")
    ledger = OUT / "request-budget.db"
    with sqlite3.connect(ledger) as connection:
        reservations = dict(connection.execute("SELECT kind,count(*) FROM reservations GROUP BY kind"))
        active_locks = connection.execute("SELECT count(*) FROM round_lock").fetchone()[0]
    calls = [call for run in runs for call in run["calls"]]
    current_db = database_contents(ROOT / "data/knowledge.db")
    aggregate = {"runs": runs, "actual_glm_requests": len(calls),
        "parameter_corrections": sum(call["purpose"] == "parameter_correction" for call in calls),
        "format_failures": sum(call.get("json_valid") is False for call in calls),
        "transport_failures": [call for call in calls if call.get("error_category") in {"timeout", "connection", "http_status"}],
        "truncations": [call for call in calls if call.get("error_category") == "truncated"],
        "other_failures": [call for call in calls if call["outcome"] != "returned" and call.get("error_category") not in {"timeout", "connection", "http_status", "truncated"}],
        "model_wait_seconds": round(sum(call["seconds"] for call in calls), 3),
        "ledger_reservations": reservations, "active_locks": active_locks,
        "all_old_evidence_unchanged": all(old_unchanged.values()), "old_evidence_files_checked": len(old_unchanged),
        "old_changed_files": [name for name, same in old_unchanged.items() if not same],
        "frozen_experiment_unchanged": all(frozen_unchanged.values()),
        "frozen_changed_files": [name for name, same in frozen_unchanged.items() if not same],
        "production_database_logically_unchanged": current_db == state["production_database"],
        "production_database": current_db, "delivery_source": code_snapshot(),
        "source_matches_live_preflight": code_snapshot() == read_json(OUT / "live/preflight.json")["code"],
        "evaluation_scope": "AI qualitative checks and program rules only; no new photos and no independent human photographer acceptance",
        "no_configuration_experiment": True, "no_github_commit_or_push": True,
    }
    write_json(OUT / "acceptance-audit.json", aggregate)
    print(json.dumps({key: aggregate[key] for key in ("actual_glm_requests", "parameter_corrections", "format_failures",
        "ledger_reservations", "all_old_evidence_unchanged", "frozen_experiment_unchanged",
        "production_database_logically_unchanged", "source_matches_live_preflight")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
