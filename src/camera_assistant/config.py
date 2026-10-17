from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from camera_assistant.image_edit_config import ImageEditSettings

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    demo_mode: bool
    api_key: str = field(repr=False)
    base_url: str
    vision_model: str
    text_model: str
    timeout_seconds: float
    max_image_mb: int
    knowledge_dir: Path
    knowledge_mode: str = "legacy"
    knowledge_db_path: Path | None = None
    preset: str = "custom"
    composition_enabled: bool = False
    detector_enabled: bool = False
    detector_device: str = "cpu"
    detector_weights_path: str = ""
    detector_python: Path | None = None
    detector_revision: str = ""
    detector_box_threshold: float = .35
    detector_text_threshold: float = .25
    detector_timeout_seconds: float = 180
    max_output_tokens: int = 4096
    disable_thinking: bool = False
    response_format: str = "prompt"
    format_retry_count: int = 1
    stream_output: bool = True
    parallel_advice: bool = True
    detector_warmup: bool = True
    image_edit: ImageEditSettings = field(default_factory=ImageEditSettings)

    def __post_init__(self) -> None:
        if self.knowledge_mode not in {"legacy", "managed"}:
            raise ValueError("KNOWLEDGE_RETRIEVAL_MODE 只能是 legacy 或 managed。")
        if self.preset not in {"custom", "glm-dino"}:
            raise ValueError("CAMERA_AI_PRESET 只能是 custom 或 glm-dino。")
        url = urlsplit(self.base_url)
        if (url.scheme not in {"http", "https"} or not url.hostname
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("模型 Base URL 必须为不含凭据、查询参数或片段的 http(s) 地址。")
        if not 1 <= self.timeout_seconds <= 600 or not 1 <= self.max_image_mb <= 100:
            raise ValueError("模型超时应为 1–600 秒，图片上限应为 1–100 MB。")
        if not 128 <= self.max_output_tokens <= 65536:
            raise ValueError("模型最大输出 token 应为 128–65536。")
        if self.response_format not in {"prompt", "json_object"}:
            raise ValueError("CAMERA_AI_RESPONSE_FORMAT 只能是 prompt 或 json_object。")
        if not isinstance(self.format_retry_count, int) or not 0 <= self.format_retry_count <= 1:
            raise ValueError("CAMERA_AI_FORMAT_RETRY_COUNT 只能是 0 或 1。")
        if self.detector_device not in {"cpu", "cuda:0"}:
            raise ValueError("检测设备只能是 cpu 或 cuda:0。")
        if not 0 <= self.detector_box_threshold <= 1 or not 0 <= self.detector_text_threshold <= 1:
            raise ValueError("检测阈值应为 0–1。")
        if not 1 <= self.detector_timeout_seconds <= 600:
            raise ValueError("检测超时应为 1–600 秒。")

    @property
    def cloud_ready(self) -> bool:
        return bool(
            not self.demo_mode
            and self.api_key
            and self.vision_model
            and self.text_model
        )

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(PROJECT_ROOT / ".env")
        preset = os.getenv("CAMERA_AI_PRESET", "custom").strip().lower()
        selected = preset == "glm-dino"
        demo_mode = _as_bool(os.getenv("APP_DEMO_MODE"), True)
        api_key = os.getenv("CAMERA_AI_API_KEY", "").strip()
        if selected and not demo_mode and not api_key:
            api_key = cls._zhipu_key()
        return cls(
            demo_mode=demo_mode,
            api_key=api_key,
            base_url=os.getenv("CAMERA_AI_BASE_URL", "").strip().rstrip("/") or (
                "https://open.bigmodel.cn/api/paas/v4" if selected else "https://api.openai.com/v1"
            ),
            vision_model=os.getenv("CAMERA_AI_VISION_MODEL", "").strip() or (
                "glm-4.6v" if selected else ""
            ),
            text_model=os.getenv("CAMERA_AI_TEXT_MODEL", "").strip() or (
                "glm-4.6v" if selected else ""
            ),
            timeout_seconds=float(os.getenv("CAMERA_AI_TIMEOUT_SECONDS", "120" if selected else "60")),
            max_image_mb=int(os.getenv("CAMERA_AI_MAX_IMAGE_MB", "15")),
            knowledge_dir=PROJECT_ROOT / "knowledge",
            knowledge_mode=os.getenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy").strip().lower(),
            knowledge_db_path=cls._knowledge_db_path(),
            preset=preset,
            composition_enabled=_as_bool(os.getenv("CAMERA_AI_COMPOSITION_ENABLED"), selected),
            detector_enabled=_as_bool(os.getenv("CAMERA_AI_DETECTOR_ENABLED"), selected),
            detector_device=os.getenv("CAMERA_AI_DETECTOR_DEVICE", "cpu").strip(),
            detector_weights_path=os.getenv("CAMERA_AI_DETECTOR_WEIGHTS_PATH", "").strip(),
            detector_python=cls._optional_path("CAMERA_AI_DETECTOR_PYTHON"),
            detector_revision=os.getenv("CAMERA_AI_DETECTOR_REVISION", "").strip() or (
                "a2bb814dd30d776dcf7e30523b00659f4f141c71" if selected else ""
            ),
            detector_box_threshold=float(os.getenv("CAMERA_AI_DETECTOR_BOX_THRESHOLD", "0.35")),
            detector_text_threshold=float(os.getenv("CAMERA_AI_DETECTOR_TEXT_THRESHOLD", "0.25")),
            detector_timeout_seconds=float(os.getenv("CAMERA_AI_DETECTOR_TIMEOUT_SECONDS", "180")),
            max_output_tokens=int(os.getenv("CAMERA_AI_MAX_OUTPUT_TOKENS", "4096")),
            disable_thinking=_as_bool(os.getenv("CAMERA_AI_DISABLE_THINKING"), False),
            response_format=os.getenv("CAMERA_AI_RESPONSE_FORMAT", "").strip().lower() or (
                "json_object" if selected else "prompt"
            ),
            format_retry_count=int(os.getenv("CAMERA_AI_FORMAT_RETRY_COUNT", "1")),
            stream_output=_as_bool(os.getenv("CAMERA_AI_STREAM_OUTPUT"), True),
            parallel_advice=_as_bool(os.getenv("CAMERA_AI_PARALLEL_ADVICE"), True),
            detector_warmup=_as_bool(os.getenv("CAMERA_AI_DETECTOR_WARMUP"), True),
            image_edit=ImageEditSettings.from_env(),
        )

    @staticmethod
    def _optional_path(name: str) -> Path | None:
        value = os.getenv(name, "").strip()
        if not value:
            return None
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @classmethod
    def _zhipu_key(cls) -> str:
        key = os.getenv("ZHIPU_API_KEY", "").strip()
        if key:
            return key
        # Only the named provider credential is reused; experimental configs are never read.
        from vision_lab_tool.credentials import KeyVault

        directory = cls._optional_path("VISION_LAB_DATA_DIR") or PROJECT_ROOT / "data/vision_lab"
        return KeyVault(directory / "credentials.dpapi.json").load().get("ZHIPU_API_KEY", "")

    @staticmethod
    def _knowledge_db_path() -> Path:
        configured = os.getenv("KNOWLEDGE_DB_PATH", "data/knowledge.db").strip()
        path = Path(configured or "data/knowledge.db").expanduser()
        return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
