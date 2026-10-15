import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("targeted_budget", Path(__file__).resolve().parents[1] / "scripts/targeted_budget.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_durable_whole_round_cap_and_duplicate_prevention(tmp_path):
    path = tmp_path / "budget.db"
    budget = module.TargetedBudget(path)
    budget.reserve("case/a", "glm")
    with pytest.raises(ValueError, match="duplicate"):
        module.TargetedBudget(path).reserve("case/a", "glm")
    for index in range(23):
        budget.reserve(f"other/{index}", "glm")
    with pytest.raises(ValueError, match="cap exhausted"):
        module.TargetedBudget(path).reserve("extra", "glm")
    budget.reserve("D17", "dino")
    budget.reserve("D01", "dino")
    with pytest.raises(ValueError, match="cap exhausted"):
        budget.reserve("P03", "dino")


def test_lock_excludes_separate_owners_and_releases_after_failure(tmp_path):
    path = tmp_path / "budget.db"
    with pytest.raises(RuntimeError), module.TargetedBudget(path).exclusive():
        with pytest.raises(ValueError, match="concurrent"), module.TargetedBudget(path).exclusive():
            pytest.fail("Second owner must never enter")
        raise RuntimeError("test failure")
    with module.TargetedBudget(path).exclusive():
        pass


def test_page_observer_installation_is_idempotent_across_streamlit_reruns(monkeypatch, tmp_path):
    import importlib

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    runner = importlib.import_module("run_targeted_acceptance")
    monkeypatch.setattr(runner, "OUT", tmp_path)
    monkeypatch.setattr(runner, "_PAGE_HOOK_INSTALLED", False)
    monkeypatch.setattr(runner.CameraAssistantPipeline, "run", runner.CameraAssistantPipeline.run)
    runner.install_page_recording()
    once = runner.CameraAssistantPipeline.run
    runner.install_page_recording()
    assert runner.CameraAssistantPipeline.run is once


def test_nested_observer_detach_restores_the_original_detector(monkeypatch, tmp_path):
    import importlib
    from types import SimpleNamespace

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    runner = importlib.import_module("run_targeted_acceptance")
    detector = SimpleNamespace(localize=lambda *args: "saved detector")
    original = detector.localize
    pipeline = SimpleNamespace(localizer=detector,
        vision_analyzer=SimpleNamespace(analyze=lambda *args: None), composition_advisor=None,
        advisor=SimpleNamespace(recommend=lambda *args: None),
        retriever=SimpleNamespace(search=lambda *args: []))
    recorder = runner.TargetedRecorder(tmp_path, "D17")
    recorder.attach(pipeline)
    assert detector.localize is not original
    recorder.detach()
    assert detector.localize is original
