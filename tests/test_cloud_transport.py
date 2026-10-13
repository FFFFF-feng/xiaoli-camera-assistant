from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from camera_assistant.config import Settings
from camera_assistant.services.cloud import ModelServiceError, extract_json, request_json


def settings() -> Settings:
    return Settings(False, "secret-test-only", "https://example.invalid/v1", "glm-4.6v",
                    "glm-4.6v", 120, 15, Path("knowledge"))


def transport(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(handler), **kwargs,
    ))


def test_request_matches_glm_experiment_and_extracts_content_list(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert str(request.url) == "https://example.invalid/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer secret-test-only"
        assert body["model"] == "glm-4.6v"
        assert body["max_tokens"] == 4096
        assert body["stream"] is False
        assert "thinking" not in body
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": [{"type": "text", "text": '{"ok":true}'}],
        }}]})
    transport(monkeypatch, handler)
    assert request_json(settings(), {"model": "glm-4.6v", "messages": []}) == {"ok": True}


@pytest.mark.parametrize("answer", ["{} trailing", '{"a":1,"a":2}', '{"a":NaN}', "[]"])
def test_invalid_json_is_rejected(answer):
    with pytest.raises(ModelServiceError):
        extract_json(answer)


def test_fenced_json_is_accepted():
    assert extract_json('```json\n{"ok":true}\n```') == {"ok": True}


@pytest.mark.parametrize("choice", [
    {"finish_reason": "length", "message": {"content": '{"ok":true}'}},
    {"finish_reason": "content_filter", "message": {"content": '{"ok":true}'}},
    {"message": {"refusal": "private remote text", "content": '{"ok":true}'}},
    {"message": {"content": None}},
])
def test_truncation_refusal_and_empty_content_are_rejected(monkeypatch, choice):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"choices": [choice]}))
    with pytest.raises(ModelServiceError) as error:
        request_json(settings(), {})
    assert "private remote text" not in str(error.value)


def test_http_error_does_not_expose_body_credentials_or_url(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(
        401, text="secret-test-only private provider body",
    ))
    with pytest.raises(ModelServiceError) as error:
        request_json(settings(), {})
    assert "401" in str(error.value)
    assert "secret-test-only" not in str(error.value)
    assert "example.invalid" not in str(error.value)


def test_settings_repr_hides_key():
    assert "secret-test-only" not in repr(settings())


def test_glm_preset_resolves_only_named_provider_vault(monkeypatch, tmp_path):
    import camera_assistant.config as module
    from vision_lab_tool.credentials import KeyVault

    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    for name in ("CAMERA_AI_API_KEY", "ZHIPU_API_KEY", "CAMERA_AI_BASE_URL",
                 "CAMERA_AI_VISION_MODEL", "CAMERA_AI_TEXT_MODEL", "VISION_LAB_DATA_DIR",
                 "CAMERA_AI_COMPOSITION_ENABLED", "CAMERA_AI_DETECTOR_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APP_DEMO_MODE", "false")
    monkeypatch.setenv("CAMERA_AI_PRESET", "glm-dino")
    monkeypatch.setattr(KeyVault, "load", lambda self: {"ZHIPU_API_KEY": "vault-test-only"})
    chosen = Settings.from_env()
    assert chosen.cloud_ready
    assert chosen.api_key == "vault-test-only"
    assert chosen.vision_model == chosen.text_model == "glm-4.6v"
    assert chosen.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert chosen.composition_enabled and chosen.detector_enabled
    monkeypatch.setenv("CAMERA_AI_API_KEY", "explicit-test-only")
    monkeypatch.setattr(KeyVault, "load", lambda self: pytest.fail("must not access vault"))
    assert Settings.from_env().api_key == "explicit-test-only"
