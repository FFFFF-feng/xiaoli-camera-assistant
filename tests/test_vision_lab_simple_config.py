import json
import os

import pytest

from vision_lab_tool import configuration
from vision_lab_tool.adapters import build_request
from vision_lab_tool.models import ModelConfig


def test_four_requested_models_are_fully_configured():
    assert hasattr(configuration, "focused_configs")
    configs = configuration.focused_configs()
    assert [c.name for c in configs] == [
        "Qwen3-VL Plus",
        "Doubao-Seed 2.1 Lite",
        "Doubao-Seed 2.1 Pro",
        "GLM-4.6V",
    ]
    assert [c.model_id for c in configs] == [
        "qwen3-vl-plus",
        "doubao-seed-2-1-lite-260915",
        "doubao-seed-2-1-pro-260915",
        "glm-4.6v",
    ]
    assert all(c.protocol == "chat" and c.base_url and c.key_env for c in configs)
    assert configs[1].key_env == configs[2].key_env == "ARK_API_KEY"
    for config in configs:
        url, _headers, body = build_request(
            config, "JSON task", "data:image/jpeg;base64,AAAA", "recognition", "local-test-token"
        )
        assert url.endswith("/chat/completions")
        assert body["model"] == config.model_id
        assert body["max_tokens"] == config.max_output == 4096
        assert "response_format" not in body and "thinking" not in body
        assert "local-test-token" not in json.dumps(body)


def test_focused_config_migration_preserves_custom_work():
    assert hasattr(configuration, "ensure_focused_configs")
    custom = ModelConfig(
        config_id="custom",
        name="我的配置",
        provider="本地",
        protocol="chat",
        base_url="http://localhost:8000/v1",
        model_id="mine",
    )
    migrated = configuration.ensure_focused_configs([custom])
    assert migrated[0] == custom
    focused = next(c for c in migrated if c.name == "Qwen3-VL Plus")
    focused.model_id = "my-edited-model"
    again = configuration.ensure_focused_configs(migrated)
    assert len(again) == len(migrated)
    assert next(c for c in again if c.config_id == focused.config_id).model_id == "my-edited-model"


def test_locally_saved_key_overrides_environment_without_entering_configs(monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "old-environment-token")
    config = ModelConfig(name="test", provider="方舟", protocol="chat", key_env="ARK_API_KEY")
    assert (
        configuration.resolve_key(config, saved={"ARK_API_KEY": "new-saved-token"})
        == "new-saved-token"
    )
    assert (
        configuration.resolve_key(config, "session-token", saved={"ARK_API_KEY": "new-saved-token"})
        == "session-token"
    )
    values = configuration.collect_secret_values([config], saved={"ARK_API_KEY": "new-saved-token"})
    assert "new-saved-token" in values and "old-environment-token" in values
    assert "new-saved-token" not in config.model_dump_json()


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI feature")
def test_windows_key_vault_roundtrip_preserves_blank_and_never_writes_plaintext(tmp_path):
    from vision_lab_tool.credentials import KeyVault

    path = tmp_path / "credentials.dpapi.json"
    vault = KeyVault(path)
    vault.update({"DASHSCOPE_API_KEY": "test-qwen-secret", "ARK_API_KEY": "test-ark-secret"})
    text = path.read_text("utf-8")
    assert "test-qwen-secret" not in text and "test-ark-secret" not in text
    reopened = KeyVault(path)
    assert reopened.load()["DASHSCOPE_API_KEY"] == "test-qwen-secret"
    reopened.update({"DASHSCOPE_API_KEY": "", "ZHIPU_API_KEY": "test-glm-secret"})
    assert reopened.load() == {
        "DASHSCOPE_API_KEY": "test-qwen-secret",
        "ARK_API_KEY": "test-ark-secret",
        "ZHIPU_API_KEY": "test-glm-secret",
    }
    reopened.delete("ARK_API_KEY")
    assert "ARK_API_KEY" not in reopened.load()


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI feature")
def test_corrupt_vault_and_invalid_values_do_not_destroy_saved_keys(tmp_path):
    from vision_lab_tool.credentials import KeyVault

    path = tmp_path / "credentials.dpapi.json"
    vault = KeyVault(path)
    vault.update({"ARK_API_KEY": "test-ark-secret"})
    previous = path.read_bytes()
    with pytest.raises(ValueError):
        vault.update({"ARK_API_KEY": "secret\ninvalid"})
    assert path.read_bytes() == previous
    path.write_text("not a key file", "utf-8")
    with pytest.raises(ValueError, match="本机密钥"):
        vault.update({"ARK_API_KEY": "new-secret"})
    assert path.read_text("utf-8") == "not a key file"
