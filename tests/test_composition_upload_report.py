import argparse
import importlib.util
from pathlib import Path

import pytest
from test_observed_composition import advice, observed

from camera_assistant.composition_models import CompositionIntent, ObservedScene
from camera_assistant.services.layout_solver import solve_layout

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_upload", ROOT / "scripts/verify_composition_upload.py")
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)


def test_upload_verification_is_explicit_and_loopback_only(capsys):
    assert verification.main(["--image", "not-read-without-live.jpg"]) == 0
    assert "未执行" in capsys.readouterr().out
    for address in ["https://example.com", "http://127.0.0.1@evil.com", "http://localhost/?key=private"]:
        with pytest.raises(argparse.ArgumentTypeError):
            verification.local_origin(address)


def test_report_checks_actual_frontend_contract_without_copying_private_text():
    sample = advice()
    board, framing = solve_layout(CompositionIntent(focus_object_id="object1", diagnosis="private-scene-text"),
                                  ObservedScene.model_validate(observed()), 1.5, sample.proposals[0])
    sample.proposals[0].storyboard = board
    sample.proposals[0].framing_plan = framing
    report = verification.summarize({"analysis_mode": "cloud", "private": "secret",
        "result": {"composition": sample.model_dump()}}, "sample-1", 3)
    assert report["success"] and report["frontend_contract_accepted"] == [True]
    assert "private" not in str(report) and "secret" not in str(report)
    empty = verification.summarize({"result": {"composition": None}}, "sample-2", 3)
    assert not empty["success"] and empty["backend_board_count"] == 0
