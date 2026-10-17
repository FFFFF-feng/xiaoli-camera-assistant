"""Explicit, isolated configuration for the optional paid reference-image editor."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ImageEditSettings:
    enabled: bool = False
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    timeout_seconds: float = 180
    input_fidelity: str = "omit"
    quality: str = "medium"

    def __post_init__(self):
        if self.base_url:
            url = urlsplit(self.base_url)
            if (not url.hostname or url.username or url.password or url.query or url.fragment
                    or (url.scheme != "https" and not (
                        url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
                    ))):
                raise ValueError("图片编辑地址必须是 HTTPS API 根地址；本机调试才允许 HTTP。")
        if not 5 <= self.timeout_seconds <= 300:
            raise ValueError("图片编辑超时应为5到300秒。")
        if self.input_fidelity not in {"omit", "high", "low"}:
            raise ValueError("图片编辑输入保真选项只能为 omit/high/low。")
        if self.quality not in {"low", "medium", "high", "auto"}:
            raise ValueError("图片编辑质量只能为 low/medium/high/auto。")
        if self.enabled and not (self.base_url and self.api_key.strip() and self.model.strip()):
            raise ValueError("开启图片编辑前请配置独立的 API 根地址、模型和密钥。")

    @property
    def configuration_id(self) -> str:
        return hashlib.sha256(f"{self.base_url}\n{self.model}".encode()).hexdigest()[:20]

    def public(self, *, demo: bool) -> dict:
        available = self.enabled and not demo
        return {"available": available,
                "provider": urlsplit(self.base_url).hostname if available else "",
                "model": self.model if available else "",
                "configuration_id": self.configuration_id if available else "",
                "message": "每次手动生成可能产生额外费用，结果仍可能失真。" if available
                else "尚未启用图片编辑服务；当前不会发送照片或产生生成费用。"}

    @classmethod
    def from_env(cls, environment=None):
        environment = os.environ if environment is None else environment
        try:
            timeout = float(environment.get("CAMERA_IMAGE_EDIT_TIMEOUT_SECONDS", "180"))
        except (ValueError, TypeError):
            raise ValueError("图片编辑超时必须为数值。") from None
        return cls(
            enabled=environment.get("CAMERA_IMAGE_EDIT_ENABLED", "false").lower() in {"1", "true", "yes"},
            base_url=environment.get("CAMERA_IMAGE_EDIT_BASE_URL", "").strip().rstrip("/"),
            api_key=environment.get("CAMERA_IMAGE_EDIT_API_KEY", "").strip(),
            model=environment.get("CAMERA_IMAGE_EDIT_MODEL", "").strip(),
            timeout_seconds=timeout,
            input_fidelity=environment.get("CAMERA_IMAGE_EDIT_INPUT_FIDELITY", "omit").strip(),
            quality=environment.get("CAMERA_IMAGE_EDIT_QUALITY", "medium").strip(),
        )
