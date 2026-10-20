import json

import pytest

from camera_assistant.knowledge.ui_helpers import assistant_web_url


def test_workbench_returns_to_current_project_web_port(tmp_path):
    (tmp_path / ".launcher").mkdir()
    (tmp_path / ".launcher/web-service.json").write_text(json.dumps({
        "project": str(tmp_path), "port": 8081, "url": "https://untrusted.invalid/",
    }), encoding="utf-8")
    assert assistant_web_url(tmp_path) == "http://127.0.0.1:8081/"


@pytest.mark.parametrize("state", [
    None, [], {}, {"project": "/another/project", "port": 8081},
    {"port": 80}, {"port": "8081"}, {"port": 65536}, {"port": True},
])
def test_workbench_rejects_foreign_or_invalid_launcher_state(tmp_path, state):
    (tmp_path / ".launcher").mkdir()
    if isinstance(state, dict) and "project" not in state:
        state = {**state, "project": str(tmp_path)}
    (tmp_path / ".launcher/web-service.json").write_text(
        json.dumps(state), encoding="utf-8"
    )
    assert assistant_web_url(tmp_path) == "http://localhost:8501/"


def test_workbench_without_launcher_state_preserves_legacy_navigation(tmp_path):
    assert assistant_web_url(tmp_path) == "http://localhost:8501/"


def test_workbench_reads_desktop_web_start_state(tmp_path):
    (tmp_path / ".launcher").mkdir()
    (tmp_path / ".launcher/web-start.json").write_text(json.dumps({
        "project_root": str(tmp_path), "url": "http://127.0.0.1:8091/",
    }), encoding="utf-8")
    assert assistant_web_url(tmp_path) == "http://127.0.0.1:8091/"
