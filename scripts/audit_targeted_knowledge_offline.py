"""Read old retrieval inputs, rerun current boundaries offline, write new evidence only."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from camera_assistant.knowledge.context import _reference_color_mode
from camera_assistant.knowledge.models import KnowledgeRecord
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.services.knowledge_citations import (
    citation_candidates,
    knowledge_evidence_text,
    review_knowledge_citations,
)


def run(root: Path, output: Path) -> None:
    baseline = root / "data/history/main-acceptance-20261014"
    cards = baseline / "knowledge/isolated-v2-cards"
    output.mkdir(parents=True, exist_ok=True)
    db = output / "offline-isolated-software-fixture.db"
    store = KnowledgeStore(db)
    fingerprints = {}
    for path in sorted(cards.glob("*.json")):
        fingerprints[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        record = KnowledgeRecord.model_validate_json(path.read_text(encoding="utf-8"))
        if store.get_revision(record.knowledge_id) is None:
            store.save_draft(record)
            store.submit(record.knowledge_id)
            store.approve(record.knowledge_id, "isolated-software-fixture-not-human-review")
            store.publish(record.knowledge_id)
    retriever = ManagedKnowledgeRetriever(store)
    cases = []
    for case in ("P03", "D17", "D01"):
        old = json.loads((baseline / f"knowledge-comparison/with/{case}-retrieval.json").read_text(
            encoding="utf-8"))[0]
        image = (baseline / f"knowledge-comparison/with/{case}-sent.jpg").read_bytes()
        image_data = "data:image/jpeg;base64," + base64.b64encode(image).decode()
        conditions = {**old["arguments"]["conditions"], "color_adjustment_requested": False,
                      "color_reshoot_requested": False,
                      "reference_color_mode": _reference_color_mode(
                          SimpleNamespace(model_image_data_url=image_data))}
        hits = retriever.search(old["query"], conditions=conditions,
                                libraries=old["arguments"]["libraries"])
        materials = json.loads(knowledge_evidence_text(hits))
        attempts = []
        for attempt_path in sorted((baseline / "knowledge-comparison/with").glob(
            f"{case}-parameters-attempt*-request.json")):
            payload = json.loads(attempt_path.read_text(encoding="utf-8"))
            attempts.append({"file": attempt_path.name,
                             "saved_request_chars": len(json.dumps(payload, ensure_ascii=False))})
        cases.append({"case": case, "type": "offline_retrieval_of_saved_query_not_new_generation",
                      "conditions": conditions,
                      "previous_document_ids": [hit["document_id"] for hit in old["hits"]],
                      "current_document_ids": [hit.document_id for hit in hits],
                      "actual_current_model_calls": 0, "new_evidence_materials": materials,
                      "saved_request_sizes": attempts})
    first = retriever.search("高光曝光细节", conditions={"motion": "static"})[0]
    principle = "重要高光可能因过曝而失去细节。"
    citation = {"claim_path": "reasons.0", "claim": principle,
                "document_id": first.document_id, "version": 2, "source_excerpt": principle}
    audit_cases = []
    for name, claim, changes in (
        ("source_principle", principle, {}),
        ("wrong_version", principle, {"version": 1}),
        ("numeric_overreach", principle + "因此使用f/8和1/125s。", {}),
        ("geometry_overreach", "旋转相机必定减少眼镜反光。", {}),
    ):
        proposal = {**citation, "claim": claim, **changes}
        recommendation = SimpleNamespace(reasons=[claim], knowledge_citations=citation_candidates(
            [proposal, {"invalid": "citation"}]))
        report = review_knowledge_citations(recommendation, [first], {})
        audit_cases.append({"case": name, "fixture_only": True,
                            "report": report.model_dump(mode="json")})
    result = {"evidence_type": "offline_software_boundary_verification",
              "api_calls": 0, "formal_published_this_run": 0,
              "independent_human_review": False,
              "old_evidence_modified": False, "source_card_sha256": fingerprints,
              "retrieval_cases": cases, "citation_boundary_cases": audit_cases,
              "limits": ["Not a new model generation or source re-verification.",
                         "No photography quality/accuracy improvement measured.",
                         "Textual applicability requirements remain conditional, not observed facts."]}
    (output / "knowledge-offline-audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=Path("data/history/main-targeted-20261015/knowledge"))
    args = parser.parse_args()
    run(Path(__file__).resolve().parents[1], args.output)
