import json
import sys
from contextlib import nullcontext
from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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
    {"demo_mode": True}, {"stream_output": False}, {"parallel_advice": False}, {"trust_env": False},
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


def test_startup_links_workbench_and_passes_its_url(monkeypatch, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(launcher, "ROOT", root)
    monkeypatch.setattr(launcher, "prepare_settings", lambda _: configured())
    monkeypatch.setattr(launcher, "build_id", lambda: "test-build")
    monkeypatch.setattr(launcher, "configuration_id", lambda settings: "test-config")
    monkeypatch.setattr(sys, "argv", ["local_web.py", "--port", "8080", "--launch-id", "test-launch"])

    captured = {}
    app = Mock()
    app.get.return_value = lambda fn: fn

    def create_app(settings, sessions, frontend, **kwargs):
        captured["kwargs"] = kwargs
        return app

    import uvicorn

    from camera_assistant import web_app

    monkeypatch.setattr(web_app, "create_web_app", create_app)
    run = Mock()
    monkeypatch.setattr(uvicorn, "run", run)
    start = Mock(return_value="http://127.0.0.1:8503/")
    fake = SimpleNamespace(
        LaunchError=RuntimeError,
        launch_lock=lambda runtime: nullcontext(),
        ensure_knowledge_workbench=start,
    )
    monkeypatch.setitem(sys.modules, "launch_apps", fake)

    launcher.main()
    start.assert_called_once_with(8503, {8080})
    assert captured["kwargs"]["knowledge_workbench_url"] == "http://127.0.0.1:8503/"
    run.assert_called_once()
