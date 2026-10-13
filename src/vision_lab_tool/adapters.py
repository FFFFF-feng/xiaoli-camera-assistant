from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from vision_lab_tool.models import Advice, ModelConfig, ModelResult, Observation, Usage
from vision_lab_tool.prompts import wire_schema
from vision_lab_tool.security import scrub


@dataclass
class Reply:
    text: str
    model: str | None
    usage: Usage
    truncated: bool = False
    refused: bool = False


def _reasoning(config, body):
    option, value = config.reasoning, config.reasoning_value
    if option == "omit":
        return
    allowed = {
        "chat": {"enable_thinking", "thinking_type", "effort"},
        "responses": {"effort"},
        "anthropic": {"budget_tokens"},
        "gemini": {"thinking_budget"},
    }
    if option not in allowed.get(config.protocol, set()):
        raise ValueError("当前协议不支持所选推理参数")
    if option == "enable_thinking":
        if value not in {"true", "false"}:
            raise ValueError("enable_thinking 只能填 true/false")
        body["enable_thinking"] = value == "true"
    elif option == "thinking_type":
        if value not in {"enabled", "disabled", "auto"}:
            raise ValueError("thinking type 只能填 enabled/disabled/auto")
        body["thinking"] = {"type": value}
    elif option == "effort":
        if value not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
            raise ValueError("未知 reasoning effort")
        if config.protocol == "responses":
            body["reasoning"] = {"effort": value}
        else:
            body["reasoning_effort"] = value
    elif option == "budget_tokens":
        budget = int(value)
        if not 1024 <= budget < config.max_output:
            raise ValueError("Anthropic budget 必须 >=1024 且小于最大输出")
        body["thinking"] = {"type": "enabled", "budget_tokens": budget}
    elif option == "thinking_budget":
        budget = int(value)
        if budget < -1:
            raise ValueError("Gemini thinkingBudget 必须 >=-1")
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": budget}


def build_request(
    config: ModelConfig, prompt: str, data_url: str, mode: str, key: str, schema_override=None
):
    if not config.model_id.strip() or not config.base_url:
        raise ValueError("真实接口必须填写 Base URL 和模型 ID")
    if any(c in config.model_id for c in ("?", "#", "/")):
        raise ValueError("模型 ID 不得包含路径、查询或片段")
    schema = schema_override if schema_override is not None else wire_schema(mode)
    headers = {"Content-Type": "application/json"}
    if config.protocol in {"chat", "responses"}:
        if key:
            headers["Authorization"] = f"Bearer {key}"
        image = {"url": data_url}
        if config.detail != "omit":
            image["detail"] = config.detail
        if config.protocol == "chat":
            url = config.base_url + "/chat/completions"
            body = {
                "model": config.model_id,
                "stream": False,
                "max_tokens": config.max_output,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": image},
                        ],
                    }
                ],
            }
            if config.structured == "json_object":
                body["response_format"] = {"type": "json_object"}
            elif config.structured == "json_schema":
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "vision_result", "strict": True, "schema": schema},
                }
        else:
            url = config.base_url + "/responses"
            body = {
                "model": config.model_id,
                "store": False,
                "max_output_tokens": config.max_output,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {
                                "type": "input_image",
                                "image_url": data_url,
                                "detail": config.detail if config.detail != "omit" else "auto",
                            },
                        ],
                    }
                ],
            }
            if config.structured == "json_object":
                body["text"] = {"format": {"type": "json_object"}}
            elif config.structured == "json_schema":
                body["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": "vision_result",
                        "strict": True,
                        "schema": schema,
                    }
                }
    elif config.protocol == "anthropic":
        if config.detail != "omit":
            raise ValueError("Anthropic 本适配器没有 detail 参数，请选择 omit")
        if config.structured == "json_object":
            raise ValueError("Anthropic 请使用 prompt 或 json_schema")
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        url = config.base_url + "/messages"
        body = {
            "model": config.model_id,
            "max_tokens": config.max_output,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": data_url.partition(",")[2],
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }
        if config.structured == "json_schema":
            body["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    elif config.protocol == "gemini":
        if config.detail != "omit":
            raise ValueError("Gemini 本适配器没有 OpenAI detail 参数，请选择 omit")
        headers["x-goog-api-key"] = key
        url = config.base_url + "/models/" + quote(config.model_id, safe="-._") + ":generateContent"
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inlineData": {
                                "mimeType": "image/jpeg",
                                "data": data_url.partition(",")[2],
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {"maxOutputTokens": config.max_output},
        }
        if config.structured != "prompt":
            body["generationConfig"]["responseMimeType"] = "application/json"
        if config.structured == "json_schema":
            body["generationConfig"]["responseJsonSchema"] = schema
    else:
        raise ValueError("模拟协议不生成网络请求")
    _reasoning(config, body)
    return url, headers, body


def parse_response(protocol: str, payload: dict) -> Reply:
    if protocol == "chat":
        choice = payload["choices"][0]
        message = choice["message"]
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if p.get("type") == "text")
        usage = payload.get("usage") or {}
        parsed = Usage(
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            cached_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
            reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            details=usage,
        )
        return Reply(
            content,
            payload.get("model"),
            parsed,
            choice.get("finish_reason") == "length",
            bool(message.get("refusal")) or choice.get("finish_reason") == "content_filter",
        )
    if protocol == "responses":
        parts = [
            part
            for item in payload.get("output", [])
            if item.get("type") == "message"
            for part in item.get("content", [])
        ]
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "output_text")
        usage = payload.get("usage") or {}
        parsed = Usage(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cached_tokens=(usage.get("input_tokens_details") or {}).get("cached_tokens"),
            reasoning_tokens=(usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
            details=usage,
        )
        truncated = (payload.get("incomplete_details") or {}).get("reason") == "max_output_tokens"
        refused = any(p.get("type") == "refusal" for p in parts)
        refused = (
            refused
            or payload.get("status") in {"failed", "cancelled"}
            or (payload.get("status") == "incomplete" and not truncated)
        )
        return Reply(text, payload.get("model"), parsed, truncated, refused)
    if protocol == "anthropic":
        text = "".join(p.get("text", "") for p in payload["content"] if p.get("type") == "text")
        usage = payload.get("usage") or {}
        parsed = Usage(
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cached_tokens=usage.get("cache_read_input_tokens"),
            cache_write_tokens=usage.get("cache_creation_input_tokens"),
            input_includes_cache=False,
            details=usage,
        )
        return Reply(
            text,
            payload.get("model"),
            parsed,
            payload.get("stop_reason") == "max_tokens",
            payload.get("stop_reason") == "refusal",
        )
    if protocol == "gemini":
        candidates = payload.get("candidates") or []
        first = candidates[0] if candidates else {}
        text = "".join(
            p.get("text", "")
            for p in (first.get("content") or {}).get("parts", [])
            if not p.get("thought", False)
        )
        usage = payload.get("usageMetadata") or {}
        parsed = Usage(
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            cached_tokens=usage.get("cachedContentTokenCount"),
            reasoning_tokens=usage.get("thoughtsTokenCount"),
            output_includes_reasoning=False,
            details=usage,
        )
        reason = first.get("finishReason")
        return Reply(
            text,
            payload.get("modelVersion"),
            parsed,
            reason == "MAX_TOKENS",
            not candidates
            or reason in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "OTHER"},
        )
    raise ValueError("未知响应协议")


def mock_answer(case: str, mode: str) -> str:
    observation = {
        "scene_labels": [{"label": "模拟测试场景", "evidence": "固定夹具，非对上传照片的真实识别"}],
        "objects": [
            {
                "object_id": "obj1",
                "label": "模拟主体",
                "bbox": [0.2, 0.15, 0.7, 0.85],
                "confidence": None,
            }
        ],
        "subject_candidates": ["obj1"],
        "main_subject_id": "obj1",
        "main_subject_determined": True,
        "environment": "unknown",
        "light": {
            "phenomena": ["模拟明暗关系"],
            "backlight": "unknown",
            "brightness_relations": "固定测试结果",
        },
        "motion": {"visible_clues": [], "inferences": []},
        "composition_clues": ["模拟边缘干扰"],
        "uncertainties": ["这不是视觉识别"],
        "clarification_questions": ["实际关注哪个主体？"],
    }
    if case == "omission":
        observation.update(
            objects=[], subject_candidates=[], main_subject_id=None, main_subject_determined=False
        )
    if case == "invalid_box":
        observation["objects"][0]["bbox"] = [0.9, 0.1, 0.2, 2]
    if case == "malformed":
        return '{"scene_labels": [ 错误 JSON'
    if mode == "recognition":
        return json.dumps(observation, ensure_ascii=False)
    proposals = [
        {
            "action_type": action,
            "goal": "模拟突出主体",
            "actions": [operation],
            "reasons": ["固定演示理由"],
            "tradeoffs": ["模拟视野减少"],
            "conditions": ["用户确认主体后"],
            "limitations": ["未实拍验证"],
            "parameters": None,
        }
        for action, operation in [
            ("crop", "在已有照片上尝试裁切边缘"),
            ("reshoot", "重新取景后拍摄并检查背景"),
        ]
    ]
    return json.dumps(
        {
            "observation": observation,
            "user_goal": "模拟目标，非真实建议",
            "equipment_facts": [],
            "unknown_conditions": ["器材未知"],
            "proposals": proposals,
        },
        ensure_ascii=False,
    )


def invoke(
    config: ModelConfig, prompt: str, data_url: str, mode: str, key: str, transport=None
) -> ModelResult:
    started = time.perf_counter()
    result = ModelResult(config=config, status="pending", call_success=False, format_pass=False)
    attempt = {"number": 1, "started_at": datetime.now(UTC).isoformat(), "network_requested": False}
    try:
        if config.protocol == "mock":
            if config.mock_case == "failure":
                result.status, result.error = "http_error", "模拟 HTTP 500；未发出网络请求"
                return result
            reply = Reply(mock_answer(config.mock_case, mode), "mock-fixture-v1", Usage())
        else:
            if config.key_env and not key:
                result.status, result.error = "authentication", "未找到配置的密钥来源；未发出请求"
                return result
            url, headers, body = build_request(config, prompt, data_url, mode, key)
            with httpx.Client(
                timeout=config.timeout, transport=transport, follow_redirects=False
            ) as client:
                attempt["network_requested"] = True
                response = client.post(url, headers=headers, json=body)
            attempt["http_status"] = response.status_code
            if not response.is_success:
                result.status = {
                    401: "authentication",
                    403: "permission_region",
                    429: "rate_limit",
                }.get(response.status_code, "http_error")
                result.error = scrub(f"HTTP {response.status_code}: {response.text[:3000]}", [key])
                return result
            try:
                payload = response.json()
            except ValueError:
                result.status, result.error = "response_parse", "服务返回的 HTTP 正文不是 JSON"
                return result
            try:
                reply = parse_response(config.protocol, payload)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                result.status = "response_parse"
                result.error = scrub(f"厂商响应结构无法解析：{type(exc).__name__}", [key])
                return result
        result.call_success = True
        result.raw_answer = scrub(reply.text, [key])
        result.actual_model = scrub(reply.model, [key])
        result.usage = Usage.model_validate(scrub(reply.usage.model_dump(), [key]))
        if reply.truncated:
            result.status, result.error = "truncated", "达到最大输出限制，最终回答被截断"
            return result
        if reply.refused:
            result.status, result.error = "refused", "服务拒绝或未完成回答，请检查权限/内容策略"
            return result
        text = reply.text.strip()
        if text.startswith("```") and text.endswith("```"):
            text = text.partition("\n")[2].rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            result.status, result.error = "json_parse", "最终回答不是可解析 JSON（保留原文）"
            return result
        try:
            validated = (Observation if mode == "recognition" else Advice).model_validate(parsed)
        except ValidationError as exc:
            result.status = "schema_validation"
            result.error = scrub(
                json.dumps(
                    exc.errors(include_input=False, include_context=False), ensure_ascii=False
                ),
                [key],
            )
            return result
        result.parsed = scrub(validated.model_dump(mode="json"), [key])
        result.status, result.format_pass = "ok", True
    except httpx.TimeoutException:
        result.status, result.error = "timeout", "请求超时；未自动重试，服务可能已产生费用"
    except httpx.RequestError as exc:
        result.status, result.error = "network_error", f"网络错误：{type(exc).__name__}"
    except (ValueError, TypeError) as exc:
        result.status, result.error = "configuration", scrub(str(exc), [key])
    except Exception as exc:  # noqa: BLE001 -- isolate configs and expose no secret-bearing traceback
        result.status, result.error = "internal_error", f"独立调用错误：{type(exc).__name__}"
    finally:
        result.elapsed_seconds = round(time.perf_counter() - started, 4)
        attempt.update(
            status=result.status,
            elapsed_seconds=result.elapsed_seconds,
        )
        result.attempts.append(attempt)
    return result
