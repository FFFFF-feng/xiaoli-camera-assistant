import os

from vision_lab_tool.models import ModelConfig

PRESETS = {
    "阿里云百炼（国内）": {
        "provider": "阿里云百炼",
        "protocol": "chat",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_id": "qwen3-vl-plus",
        "key_env": "DASHSCOPE_API_KEY",
    },
    "火山方舟": {
        "provider": "火山方舟",
        "protocol": "chat",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "key_env": "ARK_API_KEY",
    },
    "智谱": {
        "provider": "智谱",
        "protocol": "chat",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "key_env": "ZHIPU_API_KEY",
    },
    "本地兼容服务": {
        "provider": "本地",
        "protocol": "chat",
        "base_url": "http://localhost:8000/v1",
    },
    "OpenAI Responses": {
        "provider": "OpenAI",
        "protocol": "responses",
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
    },
    "Anthropic Messages": {
        "provider": "Anthropic",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "key_env": "ANTHROPIC_API_KEY",
    },
    "Gemini generateContent": {
        "provider": "Google",
        "protocol": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "key_env": "GEMINI_API_KEY",
    },
    "模拟正常": {"provider": "模拟", "protocol": "mock", "mock_case": "correct"},
    "模拟遗漏": {"provider": "模拟", "protocol": "mock", "mock_case": "omission"},
    "模拟格式错误": {"provider": "模拟", "protocol": "mock", "mock_case": "malformed"},
}

# Checked against the official model catalog on 2026-10-11. Account access is separate.
FOCUSED_PRESETS = {
    "Qwen3-VL Plus": {
        "config_id": "focused-qwen3-vl-plus",
        "provider": "阿里云百炼",
        "model_id": "qwen3-vl-plus",
        "key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "Doubao-Seed 2.1 Lite": {
        "config_id": "focused-doubao-seed-2-1-lite",
        "provider": "火山方舟",
        "model_id": "doubao-seed-2-1-lite-260915",
        "key_env": "ARK_API_KEY",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    },
    "Doubao-Seed 2.1 Pro": {
        "config_id": "focused-doubao-seed-2-1-pro",
        "provider": "火山方舟",
        "model_id": "doubao-seed-2-1-pro-260915",
        "key_env": "ARK_API_KEY",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    },
    "GLM-4.6V": {
        "config_id": "focused-glm-4-6v",
        "provider": "智谱",
        "model_id": "glm-4.6v",
        "key_env": "ZHIPU_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
    },
}


def focused_configs():
    return [
        ModelConfig(
            name=name,
            protocol="chat",
            timeout=120.0,
            max_output=4096,
            detail="omit",
            structured="prompt",
            reasoning="omit",
            **values,
        )
        for name, values in FOCUSED_PRESETS.items()
    ]


def ensure_focused_configs(configs):
    result = list(configs)
    existing = {c.config_id for c in result}
    result.extend(c for c in focused_configs() if c.config_id not in existing)
    return result


def default_configs():
    return [
        ModelConfig(name=name, config_id=f"default-{index}", **PRESETS[name])
        for index, name in enumerate(PRESETS)
    ]


def resolve_key(config, temporary="", secrets=None, saved=None):
    if temporary:
        return temporary
    if not config.key_env:
        return ""
    if (saved or {}).get(config.key_env):
        return saved[config.key_env]
    value = os.getenv(config.key_env, "")
    if value:
        return value
    return str((secrets or {}).get(config.key_env, ""))


def collect_secret_values(configs, temporary_keys=None, secrets=None, saved=None):
    temporary_keys, secrets = temporary_keys or {}, secrets or {}
    values = [resolve_key(c, temporary_keys.get(c.config_id, ""), secrets) for c in configs]
    # Include both persistent and temporary values if a temporary value overrides a key.
    values += [resolve_key(c, secrets=secrets) for c in configs]
    values += list(temporary_keys.values())
    values += list((saved or {}).values())
    values += [str(v) for k, v in secrets.items() if "key" in k.lower()]
    values += [v for k, v in os.environ.items() if "API_KEY" in k]
    return list(dict.fromkeys(value for value in values if value))
