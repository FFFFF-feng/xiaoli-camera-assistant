from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from camera_assistant.knowledge.store import KnowledgeStore
from camera_assistant.models import KnowledgeHit

LIBRARY_IDS = frozenset({"scene", "composition", "style", "technique", "equipment", "case"})


class ManagedKnowledgeRetriever:
    """发布资料的离线检索基线；每次查询读取最新发布状态，不缓存旧版本。"""

    def __init__(self, store: KnowledgeStore) -> None:
        self.store = store

    def search(
        self,
        query: str,
        top_k: int = 4,
        *,
        libraries: Sequence[str] | None = None,
        conditions: Mapping[str, Any] | None = None,
    ) -> list[KnowledgeHit]:
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 100:
            raise ValueError("top_k 必须是 1–100 的整数。")
        selected = set(libraries) if libraries is not None else LIBRARY_IDS
        if not selected <= LIBRARY_IDS:
            raise ValueError("包含未注册的知识库。")
        tokens = set(self._tokenize(query))
        if not tokens or not selected:
            return []

        revisions = [
            revision
            for revision in self._published()
            if revision.record.library_id in selected
            and self._applicable(revision.record.conditions, conditions)
        ]
        if not revisions:
            return []
        counters = [Counter(self._tokenize(self._search_text(item.record))) for item in revisions]
        frequencies: Counter[str] = Counter()
        for counter in counters:
            frequencies.update(counter.keys())

        hits: list[KnowledgeHit] = []
        for revision, counter in zip(revisions, counters, strict=True):
            score = sum(
                (math.log((len(revisions) + 1) / (frequencies[token] + 1)) + 1)
                * min(counter[token], 3)
                for token in tokens
                if counter[token]
            )
            if score <= 0:
                continue
            record = revision.record
            content = record.content
            if record.payload:
                content += "\n\n结构化资料：\n" + json.dumps(
                    record.payload, ensure_ascii=False, sort_keys=True, allow_nan=False
                )
            hits.append(
                KnowledgeHit(
                    document_id=f"{record.library_id}/{record.knowledge_id}@v{record.version}",
                    title=record.title,
                    content=content.strip(),
                    source=record.source.name,
                    score=round(score / math.sqrt(max(sum(counter.values()), 1)), 4),
                    metadata={
                        "knowledge_id": record.knowledge_id,
                        "library_id": str(record.library_id),
                        "version": str(record.version),
                        "kind": str(record.kind),
                        "review_status": "published",
                        "source_url": record.source.url or "",
                        "source_location": record.source.location or "",
                        "source_license": record.source.license or "",
                        "reviewer": revision.reviewer or "",
                        "content_hash": revision.content_hash,
                        "retrieval_backend": "managed_keyword",
                    },
                )
            )
        hits.sort(key=lambda item: (-item.score, item.document_id))
        return hits[:top_k]

    def query_structured(
        self,
        library_id: str,
        filters: Mapping[str, Any] | None = None,
        *,
        conditions: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        """精确查询已发布 payload；点路径等值查询，不猜测数值范围或摄影结论。"""
        if library_id not in LIBRARY_IDS:
            raise ValueError("未注册的知识库。")
        if filters and any(
            not isinstance(path, str) or not path or any(not part for part in path.split("."))
            for path in filters
        ):
            raise ValueError("结构化筛选字段必须是非空点路径。")
        return [
            revision
            for revision in self._published()
            if revision.record.library_id == library_id
            and self._applicable(revision.record.conditions, conditions)
            and self._matches_payload(revision.record.payload, filters or {})
        ]

    def _published(self) -> list[Any]:
        # 双重检查作为检索边界，不能因未来存储实现改动召回评测或受限资料。
        return [
            revision
            for revision in self.store.list_revisions(status="published")
            if revision.status == "published"
            and revision.record.dataset_split == "reference"
            and revision.record.source.retrieval_allowed
        ]

    @classmethod
    def _applicable(
        cls, constraints: Mapping[str, Any], observed: Mapping[str, Any] | None
    ) -> bool:
        # 不声明条件的资料可作为通用资料；有条件但未提供上下文时保守排除。
        for field, allowed in constraints.items():
            if allowed is None:
                continue
            if observed is None or field not in observed:
                return False
            actual = observed[field]
            if isinstance(allowed, list):
                if not any(cls._equal(actual, value) for value in allowed):
                    return False
            elif not cls._equal(actual, allowed):
                return False
        return True

    @classmethod
    def _matches_payload(cls, payload: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
        for path, expected in filters.items():
            value: Any = payload
            for segment in path.split("."):
                if not isinstance(value, dict) or segment not in value:
                    return False
                value = value[segment]
            if not cls._equal(value, expected):
                return False
        return True

    @classmethod
    def _equal(cls, left: Any, right: Any) -> bool:
        # Python 中 True == 1，条件匹配不能把这两种信息混为一谈。
        if isinstance(left, bool) or isinstance(right, bool):
            return type(left) is type(right) and left == right
        if isinstance(left, dict) or isinstance(right, dict):
            return (
                isinstance(left, dict)
                and isinstance(right, dict)
                and left.keys() == right.keys()
                and all(cls._equal(value, right[key]) for key, value in left.items())
            )
        if isinstance(left, list) or isinstance(right, list):
            return (
                isinstance(left, list)
                and isinstance(right, list)
                and len(left) == len(right)
                and all(cls._equal(a, b) for a, b in zip(left, right, strict=True))
            )
        return left == right

    @staticmethod
    def _search_text(record: Any) -> str:
        return " ".join(
            (
                record.title,
                record.content,
                " ".join(record.tags),
                json.dumps(record.payload, ensure_ascii=False, sort_keys=True, allow_nan=False),
            )
        )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9.]+", text.lower())
        for sequence in re.findall(r"[\u4e00-\u9fff]+", text):
            tokens.extend(sequence)
            tokens.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))
        return tokens
