"""Three serial parameter-only pairs with frozen accepted visual/DINO evidence.

The isolated trial library has no composition cards. Its composition result is
therefore reused, and the production parameter stage and joint/final reviews run.
No visual call, detection or visual re-normalization is repeated.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import patch

from run_main_acceptance import (
    ROOT,
    AcceptanceRecorder,
    compare_knowledge,
    read_json,
    write_json,
)

sys.path.insert(0, str(ROOT / "src"))
from camera_assistant import pipeline as pipeline_module
from camera_assistant.services.scene_knowledge import SceneKnowledgeBase


def main():
    baseline = ROOT / "data/history/main-acceptance-20261014/live"
    output = ROOT / "data/history/main-acceptance-20261014/knowledge-comparison"
    knowledge = ROOT / "data/history/main-acceptance-20261014/knowledge/isolated-trial.db"
    cases = ["P03", "D17", "D01"]
    if not all(read_json(baseline / f"{case}-summary.json")["returned"] for case in cases):
        raise ValueError("All selected cases must have a complete original acceptance result")
    original_summary = AcceptanceRecorder.summary

    def factual_summary(self, **kwargs):
        result = original_summary(self, **kwargs)
        result["first_website_advice_seconds"] = None
        result["website_result_timing_note"] = "CLI parameter-only comparison; no website render performed"
        result["pipeline_return_seconds"] = result["complete_result_seconds"]
        result["transport_failures"] = [item for item in result["transport_failures"]
                                        if item["category"] in {"timeout", "connection", "http_status"}]
        result["service_failures"] = [item for item in self.calls
                                      if item.get("error_category") in {"refusal", "truncated"}]
        return result

    # These operations have already run on the saved acceptance result. Identity
    # replay enforces the same visual facts for both branches, not fabricated facts.
    with (
        patch.object(SceneKnowledgeBase, "normalize", lambda self, scene, candidates: scene),
        patch.object(pipeline_module, "normalize_scene_environment", lambda scene, request: scene),
        patch.object(AcceptanceRecorder, "summary", factual_summary),
    ):
        summary = compare_knowledge(baseline, output, cases, knowledge, "isolated_test")
    scripts = [Path(__file__), ROOT / "scripts/run_main_acceptance.py",
               ROOT / "scripts/main_round_support.py", ROOT / "scripts/run_acceptance_website.py",
               ROOT / "scripts/check_main_website.cjs"]
    write_json(output / "comparison-controls.json", {
        "cases": cases, "knowledge_state": "isolated-software-test-only",
        "formal_human_review_completed": False,
        "production_database_modified": False,
        "normalization": "frozen saved final scene; no repeated visual transformation",
        "scene_and_dino_equal_in_both_branches": all(
            item.get("scene_exactly_reused") and item.get("dino_exactly_reused")
            for item in summary["trials"]),
        "composition": "saved baseline result reused; isolated library has no composition cards",
        "actual_model_stages": ["parameters"],
        "script_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in scripts},
        "limitation": "Single output per branch; stochastic variation and deterministic final review confound causal claims",
    })
    print(f"Comparison complete: {summary['real_model_calls']} real calls", flush=True)


if __name__ == "__main__":
    main()
