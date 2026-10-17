"""Local launcher must show the current build without killing unrelated services."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_web_launcher", ROOT / "scripts/launch_web.py")
web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web)


def test_unknown_port_is_skipped_and_only_absolute_python_entry_is_owned(monkeypatch):
    monkeypatch.setattr(web, "port_taken", lambda p: p in {8080, 8081})
    monkeypatch.setattr(web, "owned_pid", lambda p: 1234 if p == 8081 else None)
    assert web.select_port(8080) == (8081, 1234)
    entry = ROOT / "scripts/start_web.py"
    assert web.command_matches(f'"D:/Python/python.exe" -u "{entry}" --port 8081', 8081)
    assert not web.command_matches('python.exe scripts/start_web.py --port 8081', 8081)
    assert not web.command_matches(f'python.exe "{entry}.bak" --port 8081', 8081)
    assert not web.command_matches(f'python.exe "{entry}" --port 8080', 8081)
    assert not web.command_matches(f'python.exe -c "{entry}" --port 8081', 8081)


def test_build_failure_does_not_reuse_or_restart_a_stale_server(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "RUNTIME", tmp_path / ".launcher")
    monkeypatch.setattr(web, "build_frontend", Mock(side_effect=web.LaunchError("构建失败")))
    selected = Mock()
    monkeypatch.setattr(web, "select_port", selected)
    with pytest.raises(web.LaunchError, match="构建失败"):
        web.launch("npm", 8080, no_browser=True)
    selected.assert_not_called()


def test_readiness_rejects_old_frontend_and_wrong_mode(monkeypatch):
    class Response:
        status = 200

        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return self.value

    for mode, page, expected in [("cloud", b"latest", True), ("cloud", b"old", False),
                                 ("demo", b"latest", False)]:
        health = ('{"service":"xiaoli-mobile-api","analysis_mode":"' + mode + '"}').encode()
        monkeypatch.setattr(web.HTTP, "open", Mock(side_effect=[Response(health), Response(page)]))
        assert web.ready(8080, b"latest", "cloud") is expected


def test_local_cloud_config_preserves_invite_and_never_uses_remote_origin(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "RUNTIME", tmp_path / ".launcher")
    monkeypatch.setattr(web.os, "environ", {})
    (tmp_path / ".env.zhipu-deploy").write_text("CAMERA_AI_API_KEY=test-only-key\nWEB_ACCESS_CODE=test-invite\n")
    environment, mode = web.local_environment(8081)
    assert mode == "cloud" and environment["CAMERA_AI_PRESET"] == "glm-dino"
    assert environment["WEB_ORIGIN"] == "http://127.0.0.1:8081"
    assert environment["WEB_ACCESS_CODE"] == "test-invite"
    assert len(environment["WEB_SESSION_SECRET"]) >= 32
    demo, mode = web.local_environment(8081, demo=True)
    assert mode == "demo" and demo["WEB_ACCESS_CODE"] == ""
    assert demo["WEB_SESSION_SECRET"] == environment["WEB_SESSION_SECRET"]


def test_optional_image_editor_check_is_disabled_by_default_and_never_reuses_vision_key(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web.os, "environ", {"CAMERA_AI_API_KEY": "test-vision-secret"})
    web.check_image_editor()
    (tmp_path / ".env").write_text("CAMERA_IMAGE_EDIT_ENABLED=true\nCAMERA_IMAGE_EDIT_BASE_URL=https://edit.invalid/v1\nCAMERA_IMAGE_EDIT_MODEL=image-model\n")
    with pytest.raises(web.LaunchError, match="独立") as error:
        web.check_image_editor()
    assert "test-vision-secret" not in str(error.value)
