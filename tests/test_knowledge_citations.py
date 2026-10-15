"""Offline claim/source boundaries; fixture publication never touches the formal library."""

import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from camera_assistant.knowledge.models import KnowledgeRecord
from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import KnowledgeHit

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "data/history/main-acceptance-20261014/knowledge/isolated-v2-cards"
PRINCIPLE = "重要高光可能因过曝而失去细节。"


def citation_module():
    name = "camera_assistant.services.knowledge_citations"
    assert importlib.util.find_spec(name), "Production needs a claim-level citation boundary"
    return importlib.import_module(name)


@pytest.fixture
def isolated_retriever(tmp_path):
    store = KnowledgeStore(tmp_path / "software-fixture-only.db")
    for path in sorted(CARDS.glob("*.json")):
        record = KnowledgeRecord.model_validate_json(path.read_text(encoding="utf-8"))
        store.save_draft(record)
        store.submit(record.knowledge_id)
        store.approve(record.knowledge_id, "software-fixture-reviewer-not-human-approval")
        store.publish(record.knowledge_id)
    return ManagedKnowledgeRetriever(store)


def hit(**metadata):
    return KnowledgeHit(
        document_id="technique/technique-exposure-clipping-001@v2",
        title="曝光调整先观察重要高光与主体细节",
        content=PRINCIPLE,
        source="Wikibooks contributors",
        metadata={
            "version": "2", "body": PRINCIPLE, "conditions": "{}",
            "source_url": "https://en.wikibooks.org/wiki/Digital_Photography/Taking_Digital_Photos",
            "source_license": "CC BY-SA 4.0", "numeric_defaults": "null",
            **metadata,
        },
    )


def candidate(**updates):
    return {
        "claim_path": "reasons.0", "claim": PRINCIPLE,
        "document_id": hit().document_id, "version": 2, "source_excerpt": PRINCIPLE,
        **updates,
    }


def review(citations, reasons=None, hits=None, conditions=None):
    module = citation_module()
    recommendation = SimpleNamespace(
        knowledge_citations=module.citation_candidates(citations),
        reasons=reasons if reasons is not None else [PRINCIPLE], risks=[], adjustments=[],
        aperture="f/8", shutter_speed="1/125s",
    )
    return module.review_knowledge_citations(recommendation, hits or [hit()], conditions)


def test_current_exact_source_principle_is_traceable():
    report = review([candidate()])
    assert len(report.accepted) == 1
    accepted = report.accepted[0]
    assert accepted.citation.document_id == hit().document_id
    assert accepted.source_url == hit().metadata["source_url"]
    assert accepted.support_scope == "quoted_general_principle"
    assert not report.rejected


def test_contiguous_complete_source_principles_are_not_rejected_merely_for_two_sentences():
    source = PRINCIPLE + "试拍检查重要高光与主体细节，依据测光和预览调整曝光。"
    report = review([candidate(claim=source, source_excerpt=source)], reasons=[source],
                    hits=[hit(body=source)])
    assert len(report.accepted) == 1
    assert not report.rejected


@pytest.mark.parametrize("changes", [
    {"document_id": "technique/elsewhere@v2"}, {"version": 1},
    {"document_id": "technique/technique-exposure-clipping-001@v1"},
])
def test_only_this_request_document_id_and_version_can_be_cited(changes):
    report = review([candidate(**changes)])
    assert not report.accepted
    assert len(report.rejected) == 1


@pytest.mark.parametrize("claim", [
    PRINCIPLE + " 所以使用f/8、1/125s和ISO100。",
    "现场有足够的照度，因此ISO100够用。",
    "向侧面旋转相机即可减少眼镜反光。",
    "f/8保证近处与远处同时清晰。",
])
def test_card_presence_cannot_support_numeric_scene_or_geometry_claims(claim):
    report = review([candidate(claim=claim)], reasons=[claim])
    assert not report.accepted
    assert len(report.rejected) == 1


def test_numeric_parameter_cannot_be_disguised_as_a_general_principle():
    report = review([candidate(claim_path="shutter_speed", claim="1/125s")])
    assert not report.accepted


def test_source_excerpt_must_exist_in_the_injected_body():
    report = review([candidate(source_excerpt="旋转相机可消除眼镜反光。")])
    assert not report.accepted
    assert "source_excerpt_not_found" in report.rejected[0].reason


def test_citation_cannot_survive_final_text_replacement():
    report = review([candidate()], reasons=["现场试拍检查曝光。"])
    assert not report.accepted
    assert "final_claim_changed" in report.rejected[0].reason


def test_unknown_required_condition_never_counts_as_satisfied():
    report = review([candidate()], hits=[hit(conditions='{"motion":["slow","fast"]}')],
                    conditions={"motion": "unknown"})
    assert not report.accepted
    assert "conditions_not_met" in report.rejected[0].reason


def test_one_malformed_citation_is_isolated_without_losing_valid_advice():
    report = review([candidate(), {"version": "invented"}, "invalid"])
    assert len(report.accepted) == 1
    assert len(report.rejected) == 2


def test_evidence_serializes_stable_identity_body_source_and_conditions():
    module = citation_module()
    evidence = json.loads(module.knowledge_evidence_text([hit(conditions='{"motion":"slow"}')]))
    assert evidence[0]["document_id"] == hit().document_id
    assert evidence[0]["version"] == 2
    assert evidence[0]["title"] == hit().title
    assert evidence[0]["body"] == PRINCIPLE
    assert evidence[0]["source"]["url"] == hit().metadata["source_url"]
    assert evidence[0]["conditions"] == {"motion": "slow"}


def test_monochrome_reflection_does_not_recall_white_balance(isolated_retriever):
    hits = isolated_retriever.search(
        "黑白人像 眼睛突出 减少眼镜反光 保留亲近感 参考亮度 medium 光线 unknown",
        conditions={"motion": "slow", "reference_color_mode": "monochrome"},
    )
    assert not any("white-balance" in item.document_id for item in hits)


def test_irrelevant_wb_excluded_without_diagnosed_colour_or_requested_colour_goal(
    isolated_retriever,
):
    hits = isolated_retriever.search(
        "温室玻璃棚 通道纵深 保留高光和阴影细节 设备 Canon R50",
        conditions={"motion": "static"},
    )
    assert any("exposure-clipping" in item.document_id for item in hits)
    assert not any("white-balance" in item.document_id for item in hits)


def test_explicit_color_goal_can_retrieve_wb_as_a_conditional_principle(isolated_retriever):
    hits = isolated_retriever.search(
        "彩色重拍希望纠正色偏并调整白平衡",
        conditions={"color_adjustment_requested": True, "color_reshoot_requested": True},
    )
    assert any("white-balance" in item.document_id for item in hits)


def test_source_license_and_shared_single_characters_are_not_relevance(isolated_retriever):
    assert isolated_retriever.search("CC BY-SA Wikibooks contributors wikipedia", conditions={}) == []
    assert isolated_retriever.search("明亮深邃的微笑", conditions={}) == []


def test_managed_hit_carries_the_exact_machine_conditions(isolated_retriever):
    hits = isolated_retriever.search("快门 运动 模糊", conditions={"motion": "slow"})
    motion = next(item for item in hits if "shutter-motion" in item.document_id)
    assert json.loads(motion.metadata["conditions"]) == {"motion": ["slow", "fast"]}
    assert motion.metadata["body"]


def test_unknown_literal_does_not_satisfy_a_required_condition():
    assert not ManagedKnowledgeRetriever._applicable({"motion": ["unknown", "fast"]},
                                                   {"motion": "unknown"})


@pytest.mark.parametrize("conditions", [None, "not-json", "[]", "null"])
def test_missing_or_invalid_machine_conditions_cannot_be_certified(conditions):
    source = hit()
    if conditions is None:
        source.metadata.pop("conditions")
    else:
        source.metadata["conditions"] = conditions
    report = review([candidate()], hits=[source])
    assert not report.accepted
    assert report.rejected[0].reason == "conditions_not_declared_or_invalid"


def test_actual_parameter_request_contains_identity_and_only_model_output_fields(monkeypatch, tmp_path):
    from test_parameter_recovery import answer
    from test_real_pipeline import settings as settings_fixture

    from camera_assistant.models import SceneAnalysis, UserRequest
    from camera_assistant.services import advisor
    from camera_assistant.services.camera_knowledge import CameraKnowledgeBase

    settings = settings_fixture.__wrapped__(tmp_path)
    observed = SceneAnalysis(scene_type="portrait", subject="person", environment="unknown",
        lighting="unknown", brightness="medium", backlight=False, subject_motion="unknown",
        dynamic_range="medium", desired_effects=[], confidence=.5)
    camera = CameraKnowledgeBase(ROOT / "knowledge/cameras/camera_profiles.yaml").resolve(
        "canon_eos_r50", "APS-C")
    sent = []

    def request(config, payload):
        sent.append(payload)
        return answer(knowledge_citations=[candidate(), {"bad": "reference"}])

    monkeypatch.setattr(advisor, "request_json", request)
    result = advisor.OpenAICompatibleRecommendationAdvisor(settings).recommend(
        UserRequest(intent="检查重要高光"), observed, [hit()], camera)
    prompt = sent[0]["messages"][0]["content"]
    assert hit().document_id in prompt
    assert '"version":2' in prompt
    assert '"conditions":{}' in prompt
    schema = json.loads(prompt.split("JSON Schema：", 1)[1])
    assert "knowledge_citations" in schema["properties"]
    assert not {"validation_notes", "safety_notes", "reviewed_operations", "exposure_state"}.intersection(
        schema["properties"])
    assert len(result.knowledge_citations) == 2


def test_software_fixture_usage_scope_is_injected(isolated_retriever):
    module = citation_module()
    hits = isolated_retriever.search("高光曝光细节", conditions={"motion": "static"})
    assert hits and all(item.metadata["usage_scope"] == "isolated_test" for item in hits)
    assert all(item["usage_scope"] == "isolated_test"
               for item in json.loads(module.knowledge_evidence_text(hits)))


def test_model_retrieval_terms_cannot_override_no_user_colour_goal(isolated_retriever):
    hits = isolated_retriever.search(
        "温室高光 阴影 white balance 白平衡",
        conditions={"motion": "static", "color_adjustment_requested": False},
    )
    assert not any("white-balance" in item.document_id for item in hits)
