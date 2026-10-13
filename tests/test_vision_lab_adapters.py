import json

import httpx
import pytest

from vision_lab_tool.adapters import build_request, invoke, mock_answer, parse_response
from vision_lab_tool.models import ModelConfig
from vision_lab_tool.security import scrub


@pytest.mark.parametrize(
    "protocol,path,image_key",
    [
        ("chat", "/v1/chat/completions", "image_url"),
        ("responses", "/v1/responses", "input_image"),
        ("anthropic", "/v1/messages", "base64"),
        ("gemini", "/v1/models/manual-model:generateContent", "inlineData"),
    ],
)
def test_request_has_distinct_protocol(protocol, path, image_key):
    config = ModelConfig(
        name="test",
        provider="test",
        protocol=protocol,
        base_url="https://test.example/v1",
        model_id="manual-model",
    )
    url, headers, body = build_request(
        config, "JSON prompt", "data:image/jpeg;base64,AAAA", "recognition", "secret"
    )
    assert url.endswith(path)
    assert image_key in json.dumps(body)
    assert "secret" not in json.dumps(body) and "secret" not in url
    assert "secret" in json.dumps(headers)
    assert body.get("store", False) is False


@pytest.mark.parametrize(
    "protocol,payload,expected",
    [
        (
            "chat",
            {
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "completion_tokens_details": {"reasoning_tokens": 10},
                },
            },
            (100, 20, 10),
        ),
        (
            "responses",
            {
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}],
                "status": "completed",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "output_tokens_details": {"reasoning_tokens": 10},
                },
            },
            (100, 20, 10),
        ),
        (
            "anthropic",
            {
                "content": [
                    {"type": "thinking", "thinking": "DO NOT SAVE"},
                    {"type": "text", "text": "{}"},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
            (100, 20, None),
        ),
        (
            "gemini",
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "DO NOT SAVE", "thought": True}, {"text": "{}"}]
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 10,
                },
            },
            (100, 20, 10),
        ),
    ],
)
def test_response_final_text_and_usage(protocol, payload, expected):
    reply = parse_response(protocol, payload)
    assert reply.text == "{}"
    assert (
        reply.usage.input_tokens,
        reply.usage.output_tokens,
        reply.usage.reasoning_tokens,
    ) == expected
    assert reply.usage.output_includes_reasoning is (protocol != "gemini")


def test_unknown_usage():
    reply = parse_response("chat", {"choices": [{"message": {"content": "{}"}}]})
    assert reply.usage.input_tokens is None and reply.usage.output_tokens is None


@pytest.mark.parametrize(
    "status,expected",
    [(401, "authentication"), (403, "permission_region"), (429, "rate_limit"), (500, "http_error")],
)
def test_error_isolated_and_no_retries(status, expected):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(status, text="secret Authorization: Bearer abc")

    config = ModelConfig(
        name="test",
        provider="test",
        protocol="chat",
        base_url="https://test.example/v1",
        model_id="manual",
    )
    result = invoke(
        config,
        "prompt",
        "data:image/jpeg;base64,AAAA",
        "recognition",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    assert result.status == expected and count == 1
    assert "secret" not in result.error and "Bearer abc" not in result.error


def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("secret data:image/jpeg;base64,AAAA")

    config = ModelConfig(
        name="test",
        provider="test",
        protocol="chat",
        base_url="https://test.example/v1",
        model_id="manual",
    )
    result = invoke(
        config,
        "prompt",
        "data:image/jpeg;base64,AAAA",
        "recognition",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    assert result.status == "timeout" and "secret" not in result.error


def test_security_removes_secrets_everywhere():
    value = {
        "Authorization": "Bearer xyz",
        "key_env": "DASHSCOPE_API_KEY",
        "text": "secret data:image/jpeg;base64,AAAA",
        "inlineData": {"data": "AAAA"},
        "config": {"api_key": "xyz"},
    }
    safe = scrub(value, ["secret"])
    assert safe["key_env"] == "DASHSCOPE_API_KEY"
    assert "secret" not in json.dumps(safe) and "AAAA" not in json.dumps(safe)


def test_mock_schema_cases():
    for case, expected in [
        ("correct", "ok"),
        ("omission", "ok"),
        ("malformed", "json_parse"),
        ("invalid_box", "schema_validation"),
        ("failure", "http_error"),
    ]:
        config = ModelConfig(name=case, provider="模拟", protocol="mock", mock_case=case)
        result = invoke(config, "prompt", "", "recognition", "")
        assert result.status == expected
    assert mock_answer("correct", "advice")


def test_truncation_keeps_final_answer():
    config = ModelConfig(
        name="test",
        provider="test",
        protocol="chat",
        base_url="https://test.example/v1",
        model_id="manual",
    )

    def handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]}
        )

    result = invoke(
        config,
        "prompt",
        "data:image/jpeg;base64,AAAA",
        "recognition",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    assert result.status == "truncated" and result.raw_answer == "{"


def test_unrecognized_coordinate_unit_not_guessed():
    payload = json.loads(mock_answer("correct", "recognition"))
    payload["objects"][0]["bbox"] = [0, 0, 1000, 1000]
    config = ModelConfig(
        name="test",
        provider="test",
        protocol="chat",
        base_url="https://test.example/v1",
        model_id="manual",
    )
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}]
            },
        )
    )
    assert invoke(config, "prompt", "", "recognition", "x", transport).status == "schema_validation"


def test_custom_key_source_and_short_token_scrubbed(monkeypatch):
    from vision_lab_tool import configuration

    monkeypatch.setenv("MODEL_TOKEN", "custom-secret-value")
    config = ModelConfig(name="test", provider="local", protocol="chat", key_env="MODEL_TOKEN")
    assert hasattr(configuration, "collect_secret_values")
    values = configuration.collect_secret_values([config], {}, {})
    assert "custom-secret-value" in values
    assert "custom-secret-value" not in scrub("custom-secret-value", values)
    assert scrub("token abc", ["abc"]) == "token [REDACTED]"
