from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    demo_mode: bool
    api_key: str
    base_url: str
    vision_model: str
    text_model: str
    timeout_seconds: float
    max_image_mb: int
    knowledge_dir: Path
    knowledge_mode: str = "legacy"
    knowledge_db_path: Path | None = None

    def __post_init__(self) -> None:
        if self.knowledge_mode not in {"legacy", "managed"}:
            raise ValueError("KNOWLEDGE_RETRIEVAL_MODE 只能是 legacy 或 managed。")

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
        return cls(
            demo_mode=_as_bool(os.getenv("APP_DEMO_MODE"), True),
            api_key=os.getenv("CAMERA_AI_API_KEY", "").strip(),
            base_url=os.getenv("CAMERA_AI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            vision_model=os.getenv("CAMERA_AI_VISION_MODEL", "").strip(),
            text_model=os.getenv("CAMERA_AI_TEXT_MODEL", "").strip(),
            timeout_seconds=float(os.getenv("CAMERA_AI_TIMEOUT_SECONDS", "60")),
            max_image_mb=int(os.getenv("CAMERA_AI_MAX_IMAGE_MB", "15")),
            knowledge_dir=PROJECT_ROOT / "knowledge",
            knowledge_mode=os.getenv("KNOWLEDGE_RETRIEVAL_MODE", "legacy").strip().lower(),
            knowledge_db_path=cls._knowledge_db_path(),
        )

    @staticmethod
    def _knowledge_db_path() -> Path:
        configured = os.getenv("KNOWLEDGE_DB_PATH", "data/knowledge.db").strip()
        path = Path(configured or "data/knowledge.db").expanduser()
        return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
