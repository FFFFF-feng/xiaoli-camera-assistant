import importlib
import importlib.util

from test_knowledge_citations import PRINCIPLE, candidate, hit

from camera_assistant.composition_models import CompositionAdvice, CompositionProposal


def module():
    name = "camera_assistant.services.composition_citations"
    assert importlib.util.find_spec(name), "Composition needs the same request/version/support boundary"
    return importlib.import_module(name)


def advice():
    return CompositionAdvice(status="unverified", proposals=[CompositionProposal(
        action_type="camera_position", goal="观察高光细节", actions=["相机向右侧移动"],
        reasons=[PRINCIPLE], tradeoffs=["背景会变化"], conditions=["现场确认"],
        limitations=["未实拍"], knowledge_citations=[candidate(), candidate(version=1)],
    )])


def test_independent_composition_principle_survives_rebuilt_prose_with_remapped_link():
    service = module()
    original = service.prepare_composition_citations(advice(), [hit()], {})
    proposal = original.proposals[0].model_copy(update={"reasons": ["程序现场比较说明"]})
    final = service.finalize_composition_citations(original.model_copy(update={"proposals": [proposal]}), [hit()], {})
    assert len(final.proposals) == 1
    report = final.proposals[0].knowledge_citation_review
    assert len(report.accepted) == 1 and len(report.rejected) == 1
    citation = report.accepted[0].citation
    assert citation.claim_path == "reasons.1"
    assert final.proposals[0].reasons[1] == PRINCIPLE
    assert final.proposals[0].actions == ["相机向右侧移动"]


def test_composition_geometry_cannot_gain_support_from_a_generic_source_quote():
    service = module()
    original = advice()
    wrong = candidate(claim="向右侧移动必定消除反光。")
    original.proposals[0] = original.proposals[0].model_copy(update={
        "reasons": [wrong["claim"]], "knowledge_citations": [wrong],
    })
    prepared = service.prepare_composition_citations(original, [hit()], {})
    final = service.finalize_composition_citations(prepared, [hit()], {})
    assert not final.proposals[0].knowledge_citation_review.accepted
    assert final.proposals[0].knowledge_citation_review.rejected
    assert final.status == "unverified"
