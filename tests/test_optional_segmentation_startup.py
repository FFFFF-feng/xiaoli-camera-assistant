"""Optional model preflight never becomes a default runtime requirement."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from camera_assistant.config import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("optional_segmentation_launcher",
                                                  ROOT / "scripts/launch_web.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    for key in list(os.environ):
        if key.startswith("CAMERA_AI_SEGMENTATION_"):
            monkeypatch.delenv(key)

    def forbid_credentials(*args, **kwargs):
        raise AssertionError("Preflight must not read provider credentials")

    monkeypatch.setattr(Settings, "_zhipu_key", forbid_credentials)
    return module


def configure(launcher, text):
    (launcher.ROOT / ".env").write_text(
        "CAMERA_AI_API_KEY=unrelated-private-key\n" + text, encoding="utf-8")


def test_default_does_not_check_model_packages_or_weights(launcher, monkeypatch):
    def reject_spec(name):
        raise AssertionError(f"Default must not inspect optional dependency {name}")

    monkeypatch.setattr(importlib.util, "find_spec", reject_spec)
    assert launcher.check_segmentation()["configured_backend"] == "grabcut"


@pytest.mark.parametrize("fallback", [True, False])
def test_missing_weights_are_sanitized_and_fallback_is_explicit(launcher, capsys, fallback):
    configure(launcher, "CAMERA_AI_SEGMENTATION_BACKEND=mobile_sam\n"
              f"CAMERA_AI_SEGMENTATION_FALLBACK={str(fallback).lower()}\n")
    if fallback:
        report = launcher.check_segmentation()
        assert report["code"] == "weights_missing" and report["fallback_backend"] == "grabcut"
        output = capsys.readouterr().out
        assert "weights_missing" in output and "fallback=grabcut" in output
    else:
        with pytest.raises(launcher.LaunchError, match="weights_missing") as raised:
            launcher.check_segmentation()
        output = str(raised.value)
    assert "unrelated-private-key" not in output and str(launcher.ROOT) not in output


def test_wrong_weight_hash_fails_before_optional_imports(launcher, monkeypatch):
    weights = launcher.ROOT / "weights.pt"
    weights.write_bytes(b"local controlled fixture")
    configure(launcher, "CAMERA_AI_SEGMENTATION_BACKEND=mobile_sam\n"
              "CAMERA_AI_SEGMENTATION_FALLBACK=false\n"
              f"CAMERA_AI_SEGMENTATION_WEIGHTS_PATH={weights}\n"
              f"CAMERA_AI_SEGMENTATION_WEIGHTS_SHA256={'0' * 64}\n")

    def reject_spec(name):
        raise AssertionError("Invalid weight must not reach optional discovery")

    monkeypatch.setattr(importlib.util, "find_spec", reject_spec)
    with pytest.raises(launcher.LaunchError, match="weights_invalid") as raised:
        launcher.check_segmentation()
    assert str(weights) not in str(raised.value)


def test_present_weight_missing_packages_allow_only_configured_fallback(launcher, monkeypatch):
    weights = launcher.ROOT / "weights.pt"
    weights.write_bytes(b"a local fixture, not model quality evidence")
    configure(launcher, "CAMERA_AI_SEGMENTATION_BACKEND=mobile_sam\n"
              f"CAMERA_AI_SEGMENTATION_WEIGHTS_PATH={weights}\n")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    report = launcher.check_segmentation()
    assert report["code"] == "backend_unavailable"
    assert report["fallback_backend"] == "grabcut"
    monkeypatch.setenv("CAMERA_AI_SEGMENTATION_FALLBACK", "false")
    with pytest.raises(launcher.LaunchError, match="backend_unavailable"):
        launcher.check_segmentation()


def test_preflight_hashes_local_weights_but_does_not_claim_inference(launcher, monkeypatch):
    weights = launcher.ROOT / "weights.pt"
    weights.write_bytes(b"only startup presence is checked here")
    digest = hashlib.sha256(weights.read_bytes()).hexdigest()
    configure(launcher, "CAMERA_AI_SEGMENTATION_BACKEND=mobile_sam\n"
              "CAMERA_AI_SEGMENTATION_FALLBACK=false\n"
              f"CAMERA_AI_SEGMENTATION_WEIGHTS_PATH={weights}\n"
              f"CAMERA_AI_SEGMENTATION_WEIGHTS_SHA256={digest}\n")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: SimpleNamespace(origin="present"))
    report = launcher.check_segmentation()
    assert report["weights_sha256"] == digest
    assert report["code"] == "configuration_checked"
    assert report["inference_proven"] is False


@pytest.mark.parametrize("setting,code", [
    ("CAMERA_AI_SEGMENTATION_DEVICE=cuda:0", "device_unavailable"),
    ("CAMERA_AI_SEGMENTATION_BACKEND=private-malformed-value", "segmentation_configuration_invalid"),
    ("CAMERA_AI_SEGMENTATION_TIMEOUT_SECONDS=private-malformed-value", "segmentation_configuration_invalid"),
])
def test_invalid_configuration_cannot_pass_even_with_fallback(launcher, setting, code):
    configure(launcher, "CAMERA_AI_SEGMENTATION_FALLBACK=true\n" + setting + "\n")
    with pytest.raises(launcher.LaunchError, match=code) as raised:
        launcher.check_segmentation()
    assert "private-malformed-value" not in str(raised.value)


def test_default_launcher_and_real_health_start_with_optional_imports_forbidden(tmp_path):
    # This is a real app/health request through in-process TestClient, with no
    # cloud request or listening server. A separate interpreter proves lazy imports.
    (tmp_path / "mobile/node_modules/vite").mkdir(parents=True)
    script = tmp_path / "default_without_models.py"
    script.write_text('''import builtins
import importlib.util
import json
import sys
from pathlib import Path

forbidden = {"torch", "torchvision", "mobile_sam", "timm"}
original_import = builtins.__import__
original_spec = importlib.util.find_spec
def checked_import(name, *args, **kwargs):
    if name.split(".")[0] in forbidden:
        raise AssertionError("default imported optional model")
    return original_import(name, *args, **kwargs)
def checked_spec(name, *args, **kwargs):
    if name.split(".")[0] in forbidden:
        raise AssertionError("default inspected optional model")
    return original_spec(name, *args, **kwargs)
builtins.__import__ = checked_import
importlib.util.find_spec = checked_spec
source_root, launcher_root = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location("checked_launcher", source_root / "scripts/launch_web.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
launcher.ROOT = launcher_root
assert launcher.check_runtime()
assert launcher.check_segmentation()["configured_backend"] == "grabcut"
from camera_assistant.config import Settings
from camera_assistant.mobile_api import create_app
from fastapi.testclient import TestClient
import httpx
def no_network(*args, **kwargs):
    raise AssertionError("health must not use outbound HTTP")
httpx.HTTPTransport.handle_request = no_network
settings = Settings(True, "", "https://example.invalid", "", "", 5, 1, source_root / "knowledge")
with TestClient(create_app(settings, "startup-check-token-long-enough")) as client:
    response = client.get("/health")
    assert response.status_code == 200
    health = response.json()
    assert health["segmentation"]["configured_backend"] == "grabcut"
    assert health["segmentation"]["inference_proven"] is False
print(json.dumps({"launcher": "ok", "health": "ok", "optional_imports": "none"}))
''', encoding="utf-8")
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("CAMERA_AI_SEGMENTATION_")}
    result = subprocess.run([sys.executable, "-B", str(script), str(ROOT), str(tmp_path)],
                            check=False, env=environment, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr
    assert '"optional_imports": "none"' in result.stdout
