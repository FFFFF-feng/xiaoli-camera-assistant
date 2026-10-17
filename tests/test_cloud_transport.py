from __future__ import annotations

import json
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from camera_assistant.config import Settings
from camera_assistant.services.cloud import (
    ModelServiceError,
    cloud_session,
    extract_json,
    request_json,
)


def settings(**updates) -> Settings:
    configured = Settings(False, "secret-test-only", "https://example.invalid/v1", "glm-4.6v",
                          "glm-4.6v", 120, 15, Path("knowledge"))
    return replace(configured, **updates)


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
        assert "response_format" not in body
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": [{"type": "text", "text": '{"ok":true}'}],
        }}]})
    transport(monkeypatch, handler)
    assert request_json(settings(), {"model": "glm-4.6v", "messages": []}) == {"ok": True}


@pytest.mark.parametrize("answer", [
    "{} trailing", '{"ok":true}}', '{"a":1,"a":2}', '{"a":NaN}', "[]",
])
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


@pytest.mark.parametrize("trust_env", [True, False])
@pytest.mark.parametrize("shared", [True, False])
def test_proxy_choice_is_applied_to_shared_and_independent_clients(monkeypatch, trust_env, shared):
    real_client, choices = httpx.Client, []

    def client(**kwargs):
        choices.append(kwargs["trust_env"])
        return real_client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{
            "finish_reason": "stop", "message": {"content": '{"ok":true}'},
        }]})), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    configured = settings(trust_env=trust_env)
    with cloud_session(configured) if shared else nullcontext():
        assert request_json(configured, {}) == {"ok": True}
    assert choices == [trust_env]


def test_proxy_choice_loads_from_env_without_changing_default(monkeypatch, tmp_path):
    import camera_assistant.config as module
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(module.os, "environ", {})
    assert Settings.from_env().trust_env is True
    monkeypatch.setenv("CAMERA_AI_TRUST_ENV", "false")
    assert Settings.from_env().trust_env is False


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


def test_json_mode_is_sent_to_provider(monkeypatch):
    def handler(request):
        assert json.loads(request.content)["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": '{"ok":true}',
        }}]})

    transport(monkeypatch, handler)
    assert request_json(settings(response_format="json_object"), {}) == {"ok": True}


def test_malformed_json_is_retried_once_without_downgrading_json_mode(monkeypatch):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        content = '{"ok":true}}' if len(sent) == 1 else '{"ok":true}'
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": content,
        }}]})

    transport(monkeypatch, handler)
    payload = {"model": "glm-4.6v", "messages": [{"role": "user", "content": "分析图片"}]}
    assert request_json(settings(response_format="json_object"), payload) == {"ok": True}
    assert len(sent) == 2
    assert all(body["response_format"] == {"type": "json_object"} for body in sent)
    assert payload["messages"] == [{"role": "user", "content": "分析图片"}]


def test_malformed_json_retry_is_bounded_and_error_is_sanitized(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": '{"private provider body":"secret-test-only"}}',
        }}]})

    transport(monkeypatch, handler)
    with pytest.raises(ModelServiceError) as error:
        request_json(settings(), {})
    assert len(calls) == 2
    assert "secret-test-only" not in str(error.value)
    assert "private provider body" not in str(error.value)


def test_format_retry_can_be_disabled(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": '{"ok":true}}',
        }}]})

    transport(monkeypatch, handler)
    with pytest.raises(ModelServiceError):
        request_json(settings(format_retry_count=0), {})
    assert len(calls) == 1


@pytest.mark.parametrize("failure", ["401", "timeout", "refusal", "length", "content_filter",
                                     "invalid_envelope"])
def test_non_format_failures_are_not_retried(monkeypatch, failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "401":
            return httpx.Response(401, text="private provider body secret-test-only")
        if failure == "timeout":
            raise httpx.ReadTimeout("private provider body secret-test-only", request=request)
        if failure == "invalid_envelope":
            return httpx.Response(200, text="private provider body secret-test-only")
        message = {"content": '{"ok":true}}'}
        if failure == "refusal":
            message["refusal"] = "private provider body secret-test-only"
        return httpx.Response(200, json={"choices": [{
            "finish_reason": failure if failure != "refusal" else "stop", "message": message,
        }]})

    transport(monkeypatch, handler)
    with pytest.raises(ModelServiceError) as error:
        request_json(settings(), {})
    assert len(calls) == 1
    assert "secret-test-only" not in str(error.value)
    assert "private provider body" not in str(error.value)


@pytest.mark.parametrize("preset, expected", [("custom", "prompt"), ("glm-dino", "json_object")])
def test_response_format_env_default_follows_preset(monkeypatch, tmp_path, preset, expected):
    import camera_assistant.config as module

    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("CAMERA_AI_PRESET", preset)
    monkeypatch.delenv("CAMERA_AI_RESPONSE_FORMAT", raising=False)
    monkeypatch.delenv("CAMERA_AI_FORMAT_RETRY_COUNT", raising=False)
    configured = Settings.from_env()
    assert configured.response_format == expected
    assert configured.format_retry_count == 1


def test_response_format_and_retry_env_can_override_preset(monkeypatch, tmp_path):
    import camera_assistant.config as module

    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("APP_DEMO_MODE", "true")
    monkeypatch.setenv("CAMERA_AI_PRESET", "glm-dino")
    monkeypatch.setenv("CAMERA_AI_RESPONSE_FORMAT", "prompt")
    monkeypatch.setenv("CAMERA_AI_FORMAT_RETRY_COUNT", "0")
    configured = Settings.from_env()
    assert configured.response_format == "prompt"
    assert configured.format_retry_count == 0


@pytest.mark.parametrize("updates", [
    {"response_format": "json_schema"}, {"format_retry_count": -1}, {"format_retry_count": 2},
    {"format_retry_count": .5},
])
def test_invalid_json_settings_are_rejected(updates):
    with pytest.raises(ValueError):
        settings(**updates)
