"""多知识库的统一记录契约；审核状态只能由存储层改变。"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    JsonValue,
    StrictBool,
    TypeAdapter,
    field_validator,
    model_validator,
)

LibraryId = Literal["scene", "composition", "style", "technique", "equipment", "case"]
ReviewStatus = Literal[
    "draft",
    "pending_review",
    "needs_revision",
    "approved",
    "published",
    "retired",
]
KnowledgeKind = Literal["manufacturer_fact", "guideline", "observed_case"]


class KnowledgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceInfo(KnowledgeModel):
    name: str = Field(min_length=1, max_length=300)
    url: str = ""
    location: str = ""
    license: str = ""
    retrieval_allowed: StrictBool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("来源名称不能只包含空白")
        return value.strip()

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        value = value.strip()
        if value:
            TypeAdapter(HttpUrl).validate_python(value)
            parsed = urlsplit(value)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                raise ValueError("来源URL只能是有效的http或https地址")
            if parsed.username or parsed.password:
                raise ValueError("来源URL不能包含登录凭据")
        return value


def _validate_finite_json(value: JsonValue) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON数据不能包含NaN或Infinity")
    if isinstance(value, dict):
        for item in value.values():
            _validate_finite_json(item)
    elif isinstance(value, list):
        for item in value:
            _validate_finite_json(item)


class KnowledgeRecord(KnowledgeModel):
    knowledge_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    library_id: LibraryId
    title: str = Field(min_length=1, max_length=300)
    kind: KnowledgeKind
    content: str = ""
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    conditions: dict[str, JsonValue] = Field(default_factory=dict)
    source: SourceInfo
    author: str = Field(min_length=1, max_length=128)
    version: int = Field(default=1, ge=1, strict=True)
    schema_version: Literal[1] = 1
    dataset_split: Literal["reference", "evaluation"] = "reference"

    @field_validator("title", "author")
    @classmethod
    def validate_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("标题和作者不能只包含空白")
        return value.strip()

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("标签不能只包含空白")
        return list(dict.fromkeys(value.strip() for value in values))

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if type(value) is not int or value != 1:
            raise ValueError("schema_version必须是受支持的整数版本1")
        return value

    @field_validator("payload", "conditions")
    @classmethod
    def validate_json(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        _validate_finite_json(value)
        return value

    @model_validator(mode="after")
    def validate_body(self) -> KnowledgeRecord:
        if not self.content.strip() and not self.payload:
            raise ValueError("content与payload至少需要一项非空")
        return self


class Revision(KnowledgeModel):
    record: KnowledgeRecord
    status: ReviewStatus
    content_hash: str
    created_at: datetime
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None


class LibraryDefinition(KnowledgeModel):
    library_id: LibraryId
    name: str
    description: str


DEFAULT_LIBRARIES: tuple[LibraryDefinition, ...] = (
    LibraryDefinition(library_id="scene", name="场景知识库", description="场景定义与识别条件"),
    LibraryDefinition(library_id="composition", name="构图知识库", description="构图规则与例外"),
    LibraryDefinition(library_id="style", name="风格知识库", description="表达目标与风格条件"),
    LibraryDefinition(library_id="technique", name="拍摄技术知识库", description="拍摄原理与排查"),
    LibraryDefinition(library_id="equipment", name="器材知识库", description="器材规格及操作限制"),
    LibraryDefinition(library_id="case", name="参考案例知识库", description="经授权审核的案例记录"),
)
