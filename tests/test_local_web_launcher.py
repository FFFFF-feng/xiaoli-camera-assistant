import json
import sys
from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from camera_assistant.config import Settings

ROOT = Path(__file__).resolve().parents[1]
spec = spec_from_file_location("local_web_launcher", ROOT / "scripts/local_web.py")
launcher = module_from_spec(spec)
spec.loader.exec_module(launcher)


def configured():
    return Settings(False, "synthetic-private-key", "https://example.invalid", "vision", "text",
                    120, 15, ROOT / "knowledge")


@pytest.mark.parametrize("updates", [
    {"demo_mode": True}, {"stream_output": False}, {"parallel_advice": False},
    {"detector_warmup": False}, {"composition_enabled": True}, {"detector_enabled": True},
    {"vision_model": "another-vision"}, {"text_model": "another-text"},
    {"timeout_seconds": 60}, {"api_key": "rotated-private-key"},
    {"knowledge_db_path": ROOT / "another.db"},
])
def test_launcher_does_not_reuse_server_with_changed_runtime_configuration(updates):
    original = configured()
    assert launcher.configuration_id(original) != launcher.configuration_id(replace(original, **updates))


def test_configuration_identity_is_stable_and_does_not_disclose_private_values():
    settings = configured()
    identity = launcher.configuration_id(settings)
    assert identity == launcher.configuration_id(replace(settings))
    assert len(identity) == 20 and all(c in "0123456789abcdef" for c in identity)
    assert settings.api_key not in identity and settings.base_url not in identity


def test_check_output_survives_windows_powershell_native_pipe(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["local_web.py", "--check", "--launch-id", "test-launch"])
    monkeypatch.setattr(launcher, "ROOT", Path("/应用/摄影"))
    monkeypatch.setattr(launcher, "prepare_settings", lambda _: configured())
    monkeypatch.setattr(launcher, "build_id", lambda: "test-build")
    launcher.main()
    output = capsys.readouterr().out
    assert output.isascii()
    assert json.loads(output)["project_root"] == str(launcher.ROOT)
    assert json.loads(output)["launch_id"] == "test-launch"
    assert configured().api_key not in output
