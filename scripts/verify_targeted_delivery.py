"""Read-only final invariants, including a non-disclosing credential-value scan."""
import json
import sqlite3

from main_round_support import code_snapshot, read_json, write_json
from run_targeted_acceptance import OUT, ROOT

from camera_assistant.config import Settings


def main():
    audit = read_json(OUT / "acceptance-audit.json")
    generation = read_json(OUT / "acceptance-audit-generation.json")
    current = code_snapshot()
    old = generation["delivery_source"]["working_source_sha256"]
    new = current["working_source_sha256"]
    changed = [name for name in new if new[name] != old.get(name)]
    configured = Settings.from_env()
    credential = configured.api_key.encode("utf-8") if configured.api_key else b""
    matches = []
    if credential:
        matches = [str(path.relative_to(ROOT)) for path in OUT.rglob("*")
                   if path.is_file() and path.suffix in {".json", ".txt", ".log", ".md", ".patch"}
                   and credential in path.read_bytes()]
    with sqlite3.connect(OUT / "request-budget.db") as connection:
        usage = dict(connection.execute("SELECT kind,count(*) FROM reservations GROUP BY kind"))
        locks = connection.execute("SELECT count(*) FROM round_lock").fetchone()[0]
    ui = [read_json(path) for path in (OUT / "ui-replay-verified").glob("case-*.json")]
    tests = (OUT / "pytest-delivery.log").read_text(encoding="utf-8")
    report = {
        "real_model_calls": usage, "no_calls_after_generation": usage == {"dino": 2, "glm": 15},
        "no_active_acceptance_lock": locks == 0,
        "old_evidence_and_frozen_code_unchanged": audit["all_old_evidence_unchanged"] and audit["frozen_experiment_unchanged"],
        "production_database_logically_unchanged": audit["production_database_logically_unchanged"],
        "final_source_matches_zero_api_review": current == read_json(OUT / "post-acceptance-rule-review/summary.json")["rule_review_source"],
        "post_generation_changed_source": changed,
        "git_commit_unchanged": current["commit"] == generation["delivery_source"]["commit"],
        "test_result": "1086 passed, 1 skipped" if "1086 passed, 1 skipped" in tests else "unconfirmed",
        "verified_ui_states": len(ui), "ui_no_horizontal_overflow": all(not item["mobile_horizontal_overflow"] for item in ui),
        "ui_no_js_exceptions": all(not item["errors"] for item in ui),
        "ordinary_8501_page": read_json(OUT / "final-page-check.json"),
        "credential_value_present_in_evidence": bool(matches), "credential_match_paths": matches,
        "scope": "Technical delivery invariants only; not photographic quality or independent human knowledge review",
    }
    write_json(OUT / "delivery-verification.json", report)
    print(json.dumps({key: report[key] for key in ("real_model_calls", "no_calls_after_generation",
        "old_evidence_and_frozen_code_unchanged", "production_database_logically_unchanged",
        "final_source_matches_zero_api_review", "git_commit_unchanged", "test_result",
        "verified_ui_states", "credential_value_present_in_evidence")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
