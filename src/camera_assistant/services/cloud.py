"""Shared Chat Completions transport; errors never include credentials or response bodies."""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

import httpx

from camera_assistant.config import Settings


class ModelServiceError(ValueError):
    """A fixed, user-readable message with no remote content or credential data."""


_response_observer: ContextVar[Callable[[dict], None] | None] = ContextVar(
    "model_response_observer", default=None,
)
_stream_observer: ContextVar[Callable[[dict], None] | None] = ContextVar(
    "model_stream_observer", default=None,
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
def observe_stream(observer: Callable[[dict], None]):
    """Opt in to SSE and progress metadata; content remains private until validation.

    Events contain a request_id, phase (request_started/content/finished), cumulative
    chars and seconds. Finished events also contain complete, streamed and
    first_content_seconds, plus a fixed error_category on service failure. Complete
    describes receipt of the response; request_json still validates the final JSON.
    No text, reasoning, remote error details, headers or credentials are emitted.
    """
    token = _stream_observer.set(observer)
    try:
        yield
    finally:
        _stream_observer.reset(token)


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
    if _stream_observer.get() is not None:
        body["stream"] = True
    if settings.disable_thinking:
        body["thinking"] = {"type": "disabled"}
    if settings.response_format == "json_object":
        body["response_format"] = {"type": "json_object"}
    for attempt in range(settings.format_retry_count + 1):
        # Service failures, refusal and truncation are outside the format-only retry boundary.
        content = _request_content(settings, body)
        try:
            return extract_json(content)
        except ModelServiceError:
            if attempt == settings.format_retry_count:
                raise
    raise AssertionError("Validated retry count must allow at least one request.")


def _request_content(settings: Settings, body: dict[str, object]) -> str:
    started = time.monotonic()
    stream_observer = _stream_observer.get()
    request_id = uuid4().hex
    complete = False
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
             "usage": None, "response_content": None, "http_status": None,
             "request_id": request_id, "streamed": False, "first_content_seconds": None}
    _emit_stream(stream_observer, {
        "phase": "request_started", "request_id": request_id, "chars": 0, "seconds": 0.0,
    })
    try:
        content = _request_content_observed(settings, body, event, started)
        complete = True
        return content
    except ModelServiceError as exc:
        event.setdefault("error_category", (
            "timeout" if "超时" in str(exc) else "connection" if "无法连接" in str(exc)
            else "truncated" if "截断" in str(exc) else "http_status" if "HTTP" in str(exc)
            else "refusal" if "拒绝" in str(exc) or "未完成" in str(exc)
            else "service_response"
        ))
        raise
    finally:
        event["seconds"] = round(time.monotonic() - started, 3)
        progress = {
            "phase": "finished", "request_id": request_id,
            "chars": len(event["response_content"] or ""), "seconds": event["seconds"],
            "complete": complete, "streamed": event["streamed"],
            "first_content_seconds": event["first_content_seconds"],
        }
        if "error_category" in event:
            progress["error_category"] = event["error_category"]
        _emit_stream(stream_observer, progress)
        observer = _response_observer.get()
        if observer is not None:
            observer(event)


def _emit_stream(observer: Callable[[dict], None] | None, event: dict) -> None:
    if observer is not None:
        try:
            observer(event)
        except Exception:  # noqa: BLE001 - an optional display must not abort a paid request
            # A display callback must not interrupt an already paid model request.
            return


def _request_content_observed(
    settings: Settings, body: dict[str, object], event: dict, started: float,
) -> str:
    try:
        with httpx.Client(timeout=settings.timeout_seconds) as client:
            url = f"{settings.base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {settings.api_key}"}
            if body.get("stream") is True:
                with client.stream("POST", url, headers=headers, json=body) as response:
                    event["http_status"] = response.status_code
                    response.raise_for_status()
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() == (
                        "application/json"
                    ):
                        # Some compatible providers ignore stream; parse this same response.
                        response.read()
                        data = response.json()
                    else:
                        event["streamed"] = True
                        return _read_stream_content(response, event, started)
            else:
                response = client.post(url, headers=headers, json=body)
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
    except ModelServiceError:
        raise
    except ValueError:
        raise ModelServiceError("模型服务未返回合法响应。") from None
    content = _content_from_response(data, event)
    _observe_content(event, started, len(content))
    return content


def _observe_content(event: dict, started: float, chars: int) -> None:
    if not chars:
        return
    seconds = round(time.monotonic() - started, 3)
    if event["first_content_seconds"] is None:
        event["first_content_seconds"] = seconds
    _emit_stream(_stream_observer.get(), {
        "phase": "content", "request_id": event["request_id"],
        "chars": chars, "seconds": seconds,
    })


def _observe_usage(data: dict, event: dict) -> None:
    usage = data.get("usage")
    if isinstance(usage, dict):
        event["usage"] = {key: usage[key] for key in (
            "prompt_tokens", "completion_tokens", "total_tokens",
        ) if isinstance(usage.get(key), (int, float))}


def _content_from_response(data: object, event: dict) -> str:
    try:
        choice = data["choices"][0]
        event["finish_reason"] = choice.get("finish_reason")
        _observe_usage(data, event)
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


def _sse_events(response: httpx.Response):
    data_lines = []
    event_type = ""
    for line in response.iter_lines():
        if not line:
            if data_lines:
                yield event_type, "\n".join(data_lines)
            data_lines = []
            event_type = ""
        elif not line.startswith(":"):
            field, separator, value = line.partition(":")
            if separator and value.startswith(" "):
                value = value[1:]
            if field == "data":
                data_lines.append(value)
            elif field == "event":
                event_type = value
    # SSE dispatches only on a blank line; an EOF mid-event is incomplete.


def _read_stream_content(response: httpx.Response, event: dict, started: float) -> str:
    parts = []
    chars = 0
    done = False
    try:
        for event_type, data_text in _sse_events(response):
            if event_type == "error":
                raise ModelServiceError("模型服务返回流式错误，请稍后重试。")
            if data_text.strip() == "[DONE]":
                done = True
                break
            try:
                data = json.loads(data_text)
                if not isinstance(data, dict):
                    raise TypeError
                if "error" in data:
                    raise ModelServiceError("模型服务返回流式错误，请稍后重试。")
                _observe_usage(data, event)
                choices = data.get("choices", [])
                if not isinstance(choices, list):
                    raise TypeError
                for choice in choices:
                    if choice.get("index", 0) != 0:
                        continue
                    delta = choice.get("delta", {})
                    if not isinstance(delta, dict):
                        raise TypeError
                    if delta.get("refusal"):
                        raise ModelServiceError("模型服务拒绝了此次分析。")
                    piece = delta.get("content")
                    if isinstance(piece, list):
                        piece = "".join(item.get("text", "") for item in piece
                                        if isinstance(item, dict))
                    if piece is not None and not isinstance(piece, str):
                        raise TypeError
                    if piece:
                        if event["finish_reason"] is not None:
                            raise ModelServiceError("模型服务返回的流式消息格式无效。")
                        parts.append(piece)
                        chars += len(piece)
                        _observe_content(event, started, chars)
                    finish_reason = choice.get("finish_reason")
                    if finish_reason is not None:
                        event["finish_reason"] = finish_reason
                    if finish_reason == "length":
                        raise ModelServiceError(
                            "模型输出被截断，请增加 CAMERA_AI_MAX_OUTPUT_TOKENS 后重试。"
                        )
                    if finish_reason in {"content_filter", "sensitive"}:
                        raise ModelServiceError("模型服务未完成此次图片分析。")
            except ModelServiceError:
                raise
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                raise ModelServiceError("模型服务返回的流式消息格式无效。") from None
        if not done or event["finish_reason"] != "stop":
            event["error_category"] = "stream_incomplete"
            raise ModelServiceError("模型流式响应未完成，请重新分析。")
        content = "".join(parts)
        if not content.strip():
            raise ModelServiceError("模型没有返回分析内容。")
        return content
    finally:
        event["response_content"] = "".join(parts)
