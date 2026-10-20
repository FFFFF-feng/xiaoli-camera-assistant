"""Local launcher must show the current build without killing unrelated services."""
from __future__ import annotations

import importlib.util
import json
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


def test_local_cloud_config_needs_only_model_key_and_never_uses_remote_origin(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "RUNTIME", tmp_path / ".launcher")
    monkeypatch.setattr(web.os, "environ", {})
    (tmp_path / ".env.zhipu-deploy").write_text("CAMERA_AI_API_KEY=test-only-key\n")
    environment, mode = web.local_environment(8081)
    assert mode == "cloud" and environment["CAMERA_AI_PRESET"] == "glm-dino"
    assert environment["WEB_ORIGIN"] == "http://127.0.0.1:8081"
    assert environment["CAMERA_AI_TRUST_ENV"] == "false"
    assert len(environment["WEB_SESSION_SECRET"]) >= 32
    demo, mode = web.local_environment(8081, demo=True)
    assert mode == "demo"
    assert demo["WEB_SESSION_SECRET"] == environment["WEB_SESSION_SECRET"]


@pytest.mark.parametrize("host,explicit,expected", [
    ("https://open.bigmodel.cn/api/paas/v4", None, "false"),
    ("https://open.bigmodel.cn/api/paas/v4", "true", "true"),
    ("https://example.invalid/v1", None, None),
    ("https://example.invalid/v1", "false", "false"),
])
def test_local_proxy_choice_is_provider_scoped_and_respects_user_config(tmp_path, monkeypatch, host, explicit, expected):
    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web, "RUNTIME", tmp_path / ".launcher")
    configured = {"CAMERA_AI_API_KEY": "test-only-key",
                  "CAMERA_AI_PRESET": "glm-dino", "CAMERA_AI_BASE_URL": host}
    if explicit is not None:
        configured["CAMERA_AI_TRUST_ENV"] = explicit
    monkeypatch.setattr(web.os, "environ", configured)
    environment, mode = web.local_environment(8080)
    assert mode == "cloud"
    assert environment.get("CAMERA_AI_TRUST_ENV") == expected
    assert configured.get("CAMERA_AI_TRUST_ENV") == explicit


def test_optional_image_editor_check_is_disabled_by_default_and_never_reuses_vision_key(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "ROOT", tmp_path)
    monkeypatch.setattr(web.os, "environ", {"CAMERA_AI_API_KEY": "test-vision-secret"})
    web.check_image_editor()
    (tmp_path / ".env").write_text("CAMERA_IMAGE_EDIT_ENABLED=true\nCAMERA_IMAGE_EDIT_BASE_URL=https://edit.invalid/v1\nCAMERA_IMAGE_EDIT_MODEL=image-model\n")
    with pytest.raises(web.LaunchError, match="独立") as error:
        web.check_image_editor()
    assert "test-vision-secret" not in str(error.value)


@pytest.mark.parametrize("no_browser", [True, False])
def test_current_web_launch_includes_local_workbench_and_two_browser_pages(tmp_path, monkeypatch, no_browser):
    import importlib

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    workbench = importlib.import_module("launch_apps")
    events = []
    monkeypatch.setattr(web, "RUNTIME", tmp_path)
    monkeypatch.setattr(web, "build_frontend", lambda _: events.append("build") or b"current")
    monkeypatch.setattr(web, "select_port", lambda _: (8080, None))
    monkeypatch.setattr(web, "local_environment", lambda *args: ({}, "cloud"))

    def ensure(port, reserved):
        assert events == ["build"] and port == 8503 and reserved == {8080}
        events.append("workbench")
        return "http://127.0.0.1:8504/"

    monkeypatch.setattr(workbench, "ensure_knowledge_workbench", ensure)
    process = Mock(pid=999)
    start = Mock(side_effect=lambda *args, **kwargs: events.append("web") or process)
    monkeypatch.setattr(web.subprocess, "Popen", start)
    monkeypatch.setattr(web, "ready", lambda *args: True)
    browser = Mock()
    monkeypatch.setattr(web.webbrowser, "open", browser)
    url = web.launch("npm", 8080, no_browser=no_browser)
    assert events == ["build", "workbench", "web"]
    assert start.call_args.kwargs["env"]["WEB_KNOWLEDGE_WORKBENCH_URL"] == "http://127.0.0.1:8504/"
    metadata = json.loads((tmp_path / "web-service.json").read_text(encoding="utf-8"))
    assert metadata["knowledge_url"] == "http://127.0.0.1:8504/"
    if no_browser:
        browser.assert_not_called()
    else:
        assert [call.args[0] for call in browser.call_args_list] == [url, metadata["knowledge_url"]]


def test_workbench_failure_preserves_previous_web_and_never_opens_browser(tmp_path, monkeypatch):
    import importlib

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    workbench = importlib.import_module("launch_apps")
    monkeypatch.setattr(web, "RUNTIME", tmp_path)
    monkeypatch.setattr(web, "build_frontend", Mock(return_value=b"current"))
    monkeypatch.setattr(web, "select_port", lambda _: (8080, 123))
    monkeypatch.setattr(web, "local_environment", lambda *args: ({}, "cloud"))
    monkeypatch.setattr(workbench, "ensure_knowledge_workbench",
                        Mock(side_effect=workbench.LaunchError("测试端口耗尽")))
    kill = Mock()
    browser = Mock()
    monkeypatch.setattr(web.os, "kill", kill)
    monkeypatch.setattr(web.webbrowser, "open", browser)
    with pytest.raises(web.LaunchError, match="知识库工作台启动失败"):
        web.launch("npm", 8080)
    kill.assert_not_called()
    browser.assert_not_called()
