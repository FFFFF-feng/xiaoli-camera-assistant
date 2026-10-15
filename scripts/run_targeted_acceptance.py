"""One bounded serial acceptance; no changes to previous acceptance scripts/evidence."""
from __future__ import annotations

import argparse
import base64
import hashlib
import sys
import threading
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from main_round_support import (
    BASELINE,
    code_snapshot,
    controlled_settings,
    copy_database,
    database_contents,
    public_settings,
    read_json,
    write_json,
)
from run_main_acceptance import AcceptanceRecorder
from targeted_budget import TargetedBudget

from camera_assistant.knowledge.context import build_knowledge_conditions
from camera_assistant.models import PipelineResult, UserRequest
from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.services import cloud
from camera_assistant.services.advice_review import final_composition_review
from camera_assistant.services.composition_citations import (
    finalize_composition_citations,
    prepare_composition_citations,
)

OUT = ROOT / "data/history/main-targeted-20261015"
OLD = ROOT / "data/history/main-acceptance-20261014/live"
MANIFEST = read_json(OLD / "manifest.json")
RECORDS = {item["id"]: item for item in MANIFEST["cases"]}
LOCK = threading.Lock()
_PAGE_HOOK_INSTALLED = False


def load_saved(case):
    saved_data = read_json(OLD / f"{case}-pipeline.json")
    saved_data["inspection"]["model_image_data_url"] = "data:image/jpeg;base64," + base64.b64encode(
        (OLD / f"{case}-sent.jpg").read_bytes()).decode("ascii")
    return PipelineResult.model_validate(saved_data)


class TargetedRecorder(AcceptanceRecorder):
    def attach(self, pipeline):
        if pipeline.localizer is not None:
            original = pipeline.localizer.localize
            self.original_methods.append((pipeline.localizer, "localize", original))

            def detected(*args, **kwargs):
                TargetedBudget(OUT / "request-budget.db").reserve(f"live/{self.case}/dino", "dino")
                return original(*args, **kwargs)

            pipeline.localizer.localize = detected
        return super().attach(pipeline)

    def content(self, settings, body):
        attempt = 1 + sum(item["stage"] == self.stage for item in self.calls)
        prefix = f"{self.case}-{self.stage}-attempt{attempt}"
        if self.stage not in {"vision", "composition", "parameters"} or attempt > 2 or len(self.calls) >= 6:
            raise ValueError("Per-stage/per-image request cap exceeded; no request sent")
        TargetedBudget(OUT / "request-budget.db").reserve(
            f"{self.output.relative_to(OUT).as_posix()}/{prefix}", "glm")

        def observed(event):
            raw = event.pop("response_content", None)
            if raw is not None:
                (self.output / f"{prefix}-response-content.txt").write_text(raw, encoding="utf-8")
            event["retrieval_text_chars"] = sum(
                len(hit.get("content", "")) for record in self.retrievals
                for hit in record["hits"]
                if (self.stage == "composition") == ("composition" in record["arguments"].get("libraries", []))
            )
            event["response_content_chars"] = len(raw) if raw is not None else None
            write_json(self.output / f"{prefix}-response-metadata.json", event)

        with cloud.observe_responses(observed):
            return super().content(settings, body)

    def summary(self, **kwargs):
        summary = super().summary(**kwargs)
        summary["transport_failures"] = [item for item in summary["transport_failures"]
                                          if item["category"] in {"timeout", "connection", "http_status"}]
        summary["service_failures"] = [item for item in self.calls
                                        if item.get("error_category") in {"truncated", "refusal"}]
        summary["evaluation"] = "AI review pending; no independent human photographer acceptance"
        return summary


def freeze(folder, settings, cases):
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "preflight.json"
    if not target.exists():
        write_json(target, {"code": code_snapshot(), "settings": public_settings(settings),
                            "cases": cases, "maximum_glm_calls_whole_round": 24,
                            "maximum_dino_calls_whole_round": 2, "serial": True,
                            "checks": "docs/main-targeted-plan-20261015.md"})


def install_page_recording():
    global _PAGE_HOOK_INSTALLED
    if _PAGE_HOOK_INSTALLED:
        return
    folder = OUT / "live"
    folder.mkdir(parents=True, exist_ok=True)
    original = CameraAssistantPipeline.run

    def recorded(pipeline, image_content, request, *, on_progress=None):
        if not LOCK.acquire(blocking=False):
            raise ValueError("Targeted acceptance is serial")
        recorder = None
        result = error = None
        guard = None
        try:
            guard = TargetedBudget(OUT / "request-budget.db").exclusive()
            guard.__enter__()
            matches = [case for case in ("D17", "D01")
                       if RECORDS[case]["sha256"] == hashlib.sha256(image_content).hexdigest()]
            if len(matches) != 1:
                raise ValueError("Only frozen D17/D01 uploads are allowed in this acceptance session")
            case = matches[0]
            if request != UserRequest.model_validate(RECORDS[case]["request"]):
                raise ValueError("Browser form differs from frozen controlled input; no API call")
            if (folder / f"{case}-calls.json").exists():
                raise ValueError("Single full-flow attempt already consumed; no resubmission")
            expected = controlled_settings(BASELINE, ROOT / "data/knowledge.db", live=True)
            if public_settings(pipeline.settings) != public_settings(expected):
                raise ValueError("Page configuration differs from frozen baseline; no API call")
            freeze(folder, pipeline.settings, ["D17", "D01"])
            recorder = TargetedRecorder(folder, case)
            recorder.save()  # Claim the single attempt before sending anything.
            recorder.attach(pipeline)

            def progress(message):
                recorder.on_progress(message)
                if on_progress:
                    on_progress(message)

            with patch.object(cloud, "_request_content", recorder.content):
                result = original(pipeline, image_content, request, on_progress=progress)
            write_json(folder / f"{case}-pipeline.json", result.model_dump(mode="json"))
            return result
        except Exception as exc:
            error = exc
            raise
        finally:
            if recorder:
                recorder.detach()
                summary = recorder.summary(result=result, error=error)
                summary.update(actual_app_page_submission=True,
                               submitted_request=request.model_dump(mode="json"))
                write_json(folder / f"{recorder.case}-summary.json", summary)
            if guard:
                guard.__exit__(None, None, None)
            LOCK.release()

    CameraAssistantPipeline.run = recorded
    _PAGE_HOOK_INSTALLED = True


def conditions_for(pipeline, saved, request):
    candidates = pipeline.scene_knowledge.find_candidates(request, saved.inspection)
    canonical = next((item.subject for item in candidates if item.profile_id == saved.scene.scene_type),
                     "main subject")
    return build_knowledge_conditions(request, saved.scene, saved.camera_profile, canonical,
                                      saved.localization, inspection=saved.inspection)


def run_partial(kind):
    cases = ["B08", "D10"] if kind == "composition" else ["P03", "D17"]
    folder = OUT / kind
    source_db = ROOT / "data/history/main-acceptance-20261014/knowledge/isolated-trial.db"
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "knowledge-snapshot.db"
    if not db.exists():
        copy_database(source_db, db)
    config = controlled_settings(BASELINE, db, live=True)
    freeze(folder, config, cases)
    for case in cases:
        branches = ("only",) if kind == "composition" else ("without", "with")
        saved = load_saved(case)
        request = UserRequest.model_validate(RECORDS[case]["request"])
        for branch in branches:
            branch_dir = folder / branch
            branch_dir.mkdir(exist_ok=True)
            if (branch_dir / f"{case}-calls.json").exists():
                print(f"{case}/{branch}: already attempted; skipped", flush=True)
                continue
            pipeline = CameraAssistantPipeline(config)
            conditions = conditions_for(pipeline, saved, request)
            query = pipeline._build_query(request, saved.scene)
            libraries = (["composition", "style", "case"] if kind == "composition"
                         else ["scene", "technique", "equipment"])
            hits = ([] if branch == "without" else pipeline.retriever.search(
                query, top_k=4, libraries=libraries, conditions=conditions))
            recorder = TargetedRecorder(branch_dir, case)
            recorder.retrievals.append({"query": query, "arguments": {
                "conditions": conditions, "libraries": libraries},
                "hits": [hit.model_dump(mode="json") for hit in hits]})
            recorder.save()
            result = error = None
            print(f"{case}/{branch}: started {kind} only", flush=True)
            recorder.wrap(pipeline.composition_advisor if kind == "composition" else pipeline.advisor,
                          "recommend", kind if kind == "composition" else "parameters")
            if kind != "composition":
                recorder.wrap(pipeline.advisor, "correct_parameters", "parameters", "parameter_correction")
            try:
                with patch.object(cloud, "_request_content", recorder.content):
                    if kind == "composition":
                        advice = pipeline.composition_advisor.recommend(
                            saved.inspection, request, saved.scene, saved.localization, hits,
                            saved.camera_profile)
                        advice = prepare_composition_citations(advice, hits, conditions)
                        advice = final_composition_review(advice, saved.recommendation, request,
                                                          saved.scene, saved.camera_profile)
                        advice = finalize_composition_citations(advice, hits, conditions)
                        result = saved.model_copy(update={"composition": advice,
                                                         "composition_knowledge_hits": hits})
                    else:
                        recommendation, recovery = pipeline._parameter_stage(
                            request, saved.scene, hits, saved.camera_profile, recorder.on_progress,
                            conditions=conditions)
                        advice = prepare_composition_citations(saved.composition, saved.composition_knowledge_hits, conditions)
                        advice = final_composition_review(advice, recommendation, request,
                                                          saved.scene, saved.camera_profile)
                        advice = finalize_composition_citations(advice, saved.composition_knowledge_hits, conditions)
                        from camera_assistant.services.knowledge_citations import (
                            review_knowledge_citations,
                        )
                        result = saved.model_copy(update={
                            "recommendation": recommendation, "parameter_recovery": recovery,
                            "composition": advice, "knowledge_hits": hits,
                            "knowledge_citation_review": review_knowledge_citations(
                                recommendation, hits, conditions),
                            "knowledge_notes": ["隔离软件测试，未经独立人审；不是正式发布知识。"],
                        })
                write_json(branch_dir / f"{case}-pipeline.json", result.model_dump(mode="json"))
            except Exception as exc:  # noqa: BLE001 - preserve bounded attempt evidence even on unexpected failure
                error = exc
                print(f"{case}/{branch}: {type(exc).__name__}", flush=True)
            finally:
                recorder.detach()
                summary = recorder.summary(result=result, error=error)
                summary.update(branch=branch, execution=f"CLI {kind}-only real generation",
                               first_website_advice_seconds=None, visual_calls=0, dino_calls=0,
                               scene_exactly_reused=result.scene == saved.scene if result else None,
                               inspection_exactly_reused=result.inspection == saved.inspection if result else None,
                               dino_exactly_reused=result.localization == saved.localization if result else None)
                write_json(branch_dir / f"{case}-summary.json", summary)
                print(f"{case}/{branch}: {len(recorder.calls)} actual requests", flush=True)
    write_json(folder / "postflight.json", {"code": code_snapshot(),
               "isolated_source_database": database_contents(source_db)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["composition", "parameters"])
    with TargetedBudget(OUT / "request-budget.db").exclusive():
        run_partial(parser.parse_args().kind)
