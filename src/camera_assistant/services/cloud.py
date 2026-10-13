"""Shared Chat Completions transport; errors never include credentials or response bodies."""
from __future__ import annotations

import json
import re

import httpx

from camera_assistant.config import Settings


class ModelServiceError(ValueError):
    """A fixed, user-readable message with no remote content or credential data."""


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelServiceError("模型 JSON 包含重复字段。")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ModelServiceError("模型 JSON 包含非有限数值。")


def extract_json(content: str) -> dict[str, object]:
    fenced = re.fullmatch(r"\s*```(?:json)?\s*(\{.*\})\s*```\s*", content, re.DOTALL)
    candidate = fenced.group(1) if fenced else content.strip()
    try:
        data = json.loads(candidate, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise ModelServiceError("模型未返回合法 JSON 对象，请重新分析。") from None
    if not isinstance(data, dict):
        raise ModelServiceError("模型必须返回 JSON 对象。")
    return data


def request_json(settings: Settings, payload: dict[str, object]) -> dict[str, object]:
    body = {"stream": False, "max_tokens": settings.max_output_tokens, **payload}
    if settings.disable_thinking:
        body["thinking"] = {"type": "disabled"}
    try:
        with httpx.Client(timeout=settings.timeout_seconds) as client:
            response = client.post(
                f"{settings.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.api_key}"},
                json=body,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise ModelServiceError(
            f"模型服务返回 HTTP {exc.response.status_code}，请检查账号权限与配置。"
        ) from None
    except httpx.TimeoutException:
        raise ModelServiceError("模型服务请求超时，请稍后重试或增加超时设置。") from None
    except httpx.HTTPError:
        raise ModelServiceError("无法连接模型服务，请检查网络与接口配置。") from None
    except ValueError:
        raise ModelServiceError("模型服务未返回合法响应。") from None
    try:
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ModelServiceError("模型输出被截断，请增加 CAMERA_AI_MAX_OUTPUT_TOKENS 后重试。")
        if choice.get("finish_reason") in {"content_filter", "sensitive"}:
            raise ModelServiceError("模型服务未完成此次图片分析。")
        message = choice["message"]
        if message.get("refusal"):
            raise ModelServiceError("模型服务拒绝了此次分析。")
        content = message["content"]
        if isinstance(content, list):
            content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
        if not isinstance(content, str) or not content.strip():
            raise ModelServiceError("模型没有返回分析内容。")
    except (KeyError, IndexError, TypeError, AttributeError):
        raise ModelServiceError("模型服务返回的消息格式无效。") from None
    return extract_json(content)
