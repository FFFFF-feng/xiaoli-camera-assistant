"""Replay each old answer independently; never supply an old answer to a new retry."""
from unittest.mock import patch

from run_targeted_acceptance import (
    BASELINE,
    OLD,
    OUT,
    RECORDS,
    ROOT,
    CameraAssistantPipeline,
    UserRequest,
    controlled_settings,
    load_saved,
    read_json,
    write_json,
)

from camera_assistant.composition_models import CompositionAdvice
from camera_assistant.models import CameraRecommendation
from camera_assistant.services.advice_review import final_composition_review
from camera_assistant.services.composition import _validate_advice
from camera_assistant.services.parameter_recovery import assess_parameters


def forbidden(*args, **kwargs):
    raise AssertionError("Offline replay must not make HTTP requests")


def main():
    import httpx

    folder = OUT / "offline-replay"
    folder.mkdir(parents=True, exist_ok=False)
    pipeline = CameraAssistantPipeline(controlled_settings(BASELINE, ROOT / "data/knowledge.db", live=False))
    summaries = []
    with patch.object(httpx.Client, "post", forbidden):
        for case in ["P02", "P03", "B08", "D10", "D17", "D01"]:
            saved = load_saved(case)
            request = UserRequest.model_validate(RECORDS[case]["request"])
            for attempt in (1, 2):
                source = OLD / f"{case}-parameters-attempt{attempt}-parsed.json"
                if not source.exists():
                    continue  # A timeout/truncation has no replayable model answer.
                candidate = CameraRecommendation.model_validate(read_json(source))
                recommendation = pipeline.validator.validate(candidate, request, saved.scene, saved.camera_profile)
                recovery = assess_parameters(recommendation, request, saved.camera_profile, candidate)
                write_json(folder / f"{case}-parameters-old-attempt{attempt}-review.json", {
                    "source": str(source.relative_to(ROOT)), "new_api_calls": 0,
                    "evidence_type": "independent offline rule review of historical model answer",
                    "not_a_response_to_current_correction_prompt": True,
                    "recommendation": recommendation.model_dump(mode="json"),
                    "recovery": recovery.model_dump(mode="json"),
                })
                summaries.append({"case": case, "old_attempt": attempt,
                                  "status": recovery.status, "missing": recovery.missing_parameters,
                                  "shutter": recommendation.shutter_speed})
            raw = CompositionAdvice.model_validate(read_json(OLD / f"{case}-composition-structured-1.json"))
            advice = _validate_advice(raw, saved.localization, [], request)
            reviewed = final_composition_review(advice, saved.recommendation, request, saved.scene, saved.camera_profile)
            write_json(folder / f"{case}-composition-review.json", reviewed.model_dump(mode="json"))
    write_json(folder / "summary.json", {"api_calls": 0, "parameter_answer_reviews": summaries,
               "composition_answer_reviews": 6,
               "note": "Historical correction answers reviewed independently; no retry was simulated."})
    print("Offline evidence replay complete; zero API calls")


if __name__ == "__main__":
    main()
