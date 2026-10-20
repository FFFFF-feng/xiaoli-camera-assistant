"""APK demos reuse desktop model policy without exposing web session secrets."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def test_local_mobile_launcher_reuses_model_policy_but_not_web_session(monkeypatch, capsys):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("mobile_entry", root / "scripts/start_mobile_api.py")
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    calls = []
    def environment(port, demo):
        calls.append((port, demo))
        return {"APP_DEMO_MODE": "false", "CAMERA_AI_API_KEY": "private-test-value",
                "CAMERA_AI_TRUST_ENV": "false", "WEB_SESSION_SECRET": "not-for-mobile",
                "WEB_ORIGIN": "http://127.0.0.1:8000"}, "cloud"
    monkeypatch.setitem(sys.modules, "launch_web", SimpleNamespace(local_environment=environment))
    target = {}
    monkeypatch.setattr(entry.os, "environ", target)
    entry.apply_local_configuration(8000, False)
    assert calls == [(8000, False)]
    assert target["CAMERA_AI_TRUST_ENV"] == "false" and target["CAMERA_AI_API_KEY"]
    assert "WEB_SESSION_SECRET" not in target and "WEB_ORIGIN" not in target
    assert "private-test-value" not in capsys.readouterr().out
