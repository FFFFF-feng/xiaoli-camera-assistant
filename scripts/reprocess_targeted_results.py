"""Zero-API review of actual returned answers; never simulates a new correction."""
from __future__ import annotations

import json
from unittest.mock import patch

import httpx
from main_round_support import code_snapshot, read_json, write_json
from run_targeted_acceptance import OLD, OUT, RECORDS, load_saved

from camera_assistant.candidate_models import candidate_list
from camera_assistant.composition_models import CompositionAdvice
from camera_assistant.models import CameraRecommendation, KnowledgeHit, UserRequest
from camera_assistant.services.advice_review import final_composition_review
from camera_assistant.services.composition import _validate_advice
from camera_assistant.services.composition_citations import (
    finalize_composition_citations,
    prepare_composition_citations,
)
from camera_assistant.services.knowledge_citations import (
    citation_candidates,
    review_knowledge_citations,
)
from camera_assistant.services.parameter_recovery import assess_parameters
from camera_assistant.services.validator import RecommendationValidator


def forbidden(*args, **kwargs):
    raise AssertionError("Rule review must never send a model request")


def review_parameter(raw, request, saved, hits, conditions):
    raw = dict(raw)
    raw.update(validation_notes=[], safety_notes=[], reviewed_operations=[], exposure_state=None)
    raw["candidate_operations"] = candidate_list(raw.get("candidate_operations", []))
    raw["knowledge_citations"] = citation_candidates(raw.get("knowledge_citations"))
    candidate = CameraRecommendation.model_validate(raw)
    accepted = review_knowledge_citations(candidate, hits, conditions).accepted
    result = RecommendationValidator().validate(candidate, request, saved.scene, saved.camera_profile)
    reasons, citations = list(result.reasons), list(result.knowledge_citations)
    for entry in accepted:
        citation = entry.citation
        if citation.claim not in reasons:
            reasons.append(citation.claim)
        citations = [item.model_copy(update={"claim_path": f"reasons.{reasons.index(citation.claim)}"})
                     if item == citation else item for item in citations]
    result = result.model_copy(update={"reasons": reasons, "knowledge_citations": citations})
    return result, assess_parameters(result, request, saved.camera_profile, candidate)


def main():
    target = OUT / "post-acceptance-rule-review"
    target.mkdir(parents=True, exist_ok=False)
    audits = []
    paths = [OUT / f"live/{case}-pipeline.json" for case in ("D17", "D01")]
    paths += [OUT / f"composition/only/{case}-pipeline.json" for case in ("B08", "D10")]
    paths += [OUT / f"parameters/{branch}/{case}-pipeline.json"
              for case in ("P03", "D17") for branch in ("without", "with")]
    with patch.object(httpx.Client, "post", forbidden):
        for original in paths:
            if not original.exists():
                continue
            data = read_json(original)
            case = original.name.split("-", 1)[0]
            request = UserRequest.model_validate(RECORDS[case]["request"])
            saved = load_saved(case)
            from camera_assistant.models import SceneAnalysis
            from vision_lab_tool.detector_models import MethodResult
            saved = saved.model_copy(update={"scene": SceneAnalysis.model_validate(data["scene"]),
                "localization": MethodResult.model_validate(data["localization"]) if data["localization"] else None})
            hits = [KnowledgeHit.model_validate(hit) for hit in data["knowledge_hits"]]
            composition_hits = [KnowledgeHit.model_validate(hit) for hit in data["composition_knowledge_hits"]]
            retrievals = read_json(original.parent / f"{case}-retrieval.json")
            conditions = next((entry["arguments"].get("conditions", {}) for entry in retrievals), {})
            folder = target / original.parent.relative_to(OUT)
            folder.mkdir(parents=True, exist_ok=True)
            answers = sorted(original.parent.glob(f"{case}-parameters-attempt*-parsed.json"))
            recommendation = CameraRecommendation.model_validate(data["recommendation"])
            recovery = data["parameter_recovery"]
            answer_reviews = []
            for answer_path in answers:
                recommendation, assessed = review_parameter(read_json(answer_path), request, saved, hits, conditions)
                answer_reviews.append({"source": str(answer_path.relative_to(OUT)),
                    "shutter_speed": recommendation.shutter_speed,
                    "recovery": assessed.model_dump(mode="json")})
                recovery = assessed.model_dump(mode="json")
                for key in ("api_calls", "correction_attempted", "format_failures", "call_limit"):
                    recovery[key] = data["parameter_recovery"][key]
            compositions = sorted(original.parent.glob(f"{case}-composition-attempt*-parsed.json"))
            source = compositions[-1] if compositions else OLD / f"{case}-composition-attempt1-parsed.json"
            composition_raw = read_json(source)
            for proposal in composition_raw.get("proposals", []):
                for field in ("action_evidence", "trial_actions", "field_checks", "knowledge_citation_review"):
                    proposal.pop(field, None)
            composition = _validate_advice(CompositionAdvice.model_validate(composition_raw),
                                           saved.localization, composition_hits, request)
            composition = prepare_composition_citations(composition, composition_hits, conditions)
            composition = final_composition_review(composition, recommendation, request, saved.scene, saved.camera_profile)
            composition = finalize_composition_citations(composition, composition_hits, conditions)
            environment_notes = saved.scene.environment_context.uncertainties
            if environment_notes:
                recommendation = recommendation.model_copy(update={"risks": list(dict.fromkeys([
                    *recommendation.risks, *environment_notes]))})
                composition = composition.model_copy(update={"uncertainties": list(dict.fromkeys([
                    *composition.uncertainties, *environment_notes])), "proposals": [proposal.model_copy(update={
                        "conditions": list(dict.fromkeys([*proposal.conditions, *environment_notes])),
                    }) for proposal in composition.proposals]})
            data.update(recommendation=recommendation.model_dump(mode="json"), parameter_recovery=recovery,
                        composition=composition.model_dump(mode="json"),
                        knowledge_citation_review=review_knowledge_citations(recommendation, hits, conditions).model_dump(mode="json"))
            write_json(folder / original.name, data)
            audits.append({"original": str(original.relative_to(OUT)), "new_api_calls": 0,
                "parameter_answers_independently_reviewed": answer_reviews,
                "original_recovery": read_json(original)["parameter_recovery"], "final_rule_recovery": recovery,
                "composition_source": str(source.relative_to(OUT)) if source.is_relative_to(OUT) else str(source),
                "no_new_correction_prompt_or_simulated_response": True})
    write_json(target / "summary.json", {"api_calls": 0, "reviews": audits, "rule_review_source": code_snapshot(),
        "limitation": "Actual generation evidence is unchanged. Re-review is not a new live full-flow success or response to a newly computed correction prompt."})
    print(json.dumps({"rule_reviews": len(audits), "api_calls": 0}))


if __name__ == "__main__":
    main()
