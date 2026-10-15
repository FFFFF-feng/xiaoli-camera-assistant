"""Shared Chat Completions transport; errors never include credentials or response bodies."""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx

from camera_assistant.config import Settings


class ModelServiceError(ValueError):
    """A fixed, user-readable message with no remote content or credential data."""


class ModelFormatError(ModelServiceError):
    """Recoverable model content, distinct from service/transport failures."""


@dataclass
class RequestBudget:
    limit: int = 2
    used: int = 0
    format_failures: int = 0


_budget: ContextVar[RequestBudget | None] = ContextVar("parameter_request_budget", default=None)
_response_observer: ContextVar[Callable[[dict], None] | None] = ContextVar(
    "model_response_observer", default=None,
)


@contextmanager
def observe_responses(observer: Callable[[dict], None]):
    """Opt-in local evidence sink; never receives credentials, headers or remote errors."""
    token = _response_observer.set(observer)
    try:
        yield
    finally:
        _response_observer.reset(token)


@contextmanager
def request_budget(limit: int = 2):
    budget = RequestBudget(limit=limit)
    token = _budget.set(budget)
    try:
        yield budget
    finally:
        _budget.reset(token)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelFormatError("模型 JSON 包含重复字段。")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ModelFormatError("模型 JSON 包含非有限数值。")


def extract_json(content: str) -> dict[str, object]:
    fenced = re.fullmatch(r"\s*```(?:json)?\s*(\{.*\})\s*```\s*", content, re.DOTALL)
    candidate = fenced.group(1) if fenced else content.strip()
    try:
        data = json.loads(candidate, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise ModelFormatError("模型未返回合法 JSON 对象，请重新分析。") from None
    if not isinstance(data, dict):
        raise ModelFormatError("模型必须返回 JSON 对象。")
    return data


def request_json(settings: Settings, payload: dict[str, object]) -> dict[str, object]:
    body = {"stream": False, "max_tokens": settings.max_output_tokens, **payload}
    if settings.disable_thinking:
        body["thinking"] = {"type": "disabled"}
    if settings.response_format == "json_object":
        body["response_format"] = {"type": "json_object"}
    for attempt in range(settings.format_retry_count + 1):
        budget = _budget.get()
        if budget is not None:
            if budget.used >= budget.limit:
                raise ModelFormatError("参数阶段请求预算已用尽；请确认缺失参数后重新分析。")
            budget.used += 1
        # Service failures, refusal and truncation are outside the format-only retry boundary.
        content = _request_content(settings, body)
        try:
            return extract_json(content)
        except ModelFormatError:
            if budget is not None:
                budget.format_failures += 1
            if attempt == settings.format_retry_count or (
                budget is not None and budget.used >= budget.limit
            ):
                raise
    raise AssertionError("Validated retry count must allow at least one request.")


def _request_content(settings: Settings, body: dict[str, object]) -> str:
    started = time.monotonic()
    text_parts = []
    for message in body.get("messages", []):
        content = message.get("content", "")
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            text_parts.extend(part.get("text", "") for part in content
                              if isinstance(part, dict) and part.get("type") == "text")
    event = {"request_text_chars": sum(len(text) for text in text_parts),
             "max_output_tokens": body.get("max_tokens"), "finish_reason": None,
             "usage": None, "response_content": None, "http_status": None}
    try:
        return _request_content_observed(settings, body, event)
    except ModelServiceError as exc:
        event["error_category"] = (
            "timeout" if "超时" in str(exc) else "connection" if "无法连接" in str(exc)
            else "truncated" if "截断" in str(exc) else "http_status" if "HTTP" in str(exc)
            else "refusal" if "拒绝" in str(exc) or "未完成" in str(exc)
            else "service_response"
        )
        raise
    finally:
        event["seconds"] = round(time.monotonic() - started, 3)
        observer = _response_observer.get()
        if observer is not None:
            observer(event)


def _request_content_observed(settings: Settings, body: dict[str, object], event: dict) -> str:
    try:
        with httpx.Client(timeout=settings.timeout_seconds) as client:
            response = client.post(
                f"{settings.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.api_key}"},
                json=body,
            )
            event["http_status"] = response.status_code
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
        event["finish_reason"] = choice.get("finish_reason")
        usage = data.get("usage")
        if isinstance(usage, dict):
            event["usage"] = {key: usage[key] for key in (
                "prompt_tokens", "completion_tokens", "total_tokens",
            ) if isinstance(usage.get(key), (int, float))}
        raw_content = choice.get("message", {}).get("content")
        if isinstance(raw_content, list):
            raw_content = "".join(item.get("text", "") for item in raw_content
                                  if isinstance(item, dict))
        if isinstance(raw_content, str):
            event["response_content"] = raw_content
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
    return content
