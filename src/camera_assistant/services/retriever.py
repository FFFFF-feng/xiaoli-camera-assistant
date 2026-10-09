from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

import yaml

from camera_assistant.models import KnowledgeHit

FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


class LocalKnowledgeRetriever:
    """无需外部模型的 RAG 检索基线，后续可替换成向量检索。"""

    def __init__(self, knowledge_dir: Path) -> None:
        self.knowledge_dir = knowledge_dir
        self.documents = self._load_documents()
        self.document_tokens = [Counter(self._tokenize(self._search_text(doc))) for doc in self.documents]
        self.document_frequency = self._document_frequency()

    def search(self, query: str, top_k: int = 4) -> list[KnowledgeHit]:
        query_tokens = set(self._tokenize(query))
        if not query_tokens:
            return []

        ranked: list[KnowledgeHit] = []
        total_docs = max(len(self.documents), 1)
        for document, token_counts in zip(self.documents, self.document_tokens, strict=True):
            score = 0.0
            for token in query_tokens:
                term_count = token_counts.get(token, 0)
                if not term_count:
                    continue
                doc_frequency = self.document_frequency.get(token, 0)
                inverse_frequency = math.log((total_docs + 1) / (doc_frequency + 1)) + 1
                score += inverse_frequency * min(term_count, 3)

            if score <= 0:
                continue
            normalized = score / math.sqrt(max(sum(token_counts.values()), 1))
            ranked.append(document.model_copy(update={"score": round(normalized, 4)}))

        ranked.sort(key=lambda item: item.score, reverse=True)
        return ranked[:top_k]

    def _load_documents(self) -> list[KnowledgeHit]:
        documents: list[KnowledgeHit] = []
        for path in sorted(self.knowledge_dir.rglob("*.md")):
            raw = path.read_text(encoding="utf-8")
            match = FRONT_MATTER.match(raw)
            if match:
                metadata = {
                    str(key): str(value)
                    for key, value in (yaml.safe_load(match.group(1)) or {}).items()
                }
                content = match.group(2).strip()
            else:
                metadata = {}
                content = raw.strip()

            title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            title = title_match.group(1).strip() if title_match else path.stem
            source = metadata.pop("source", "自建摄影知识库")
            documents.append(
                KnowledgeHit(
                    document_id=path.relative_to(self.knowledge_dir).as_posix(),
                    title=title,
                    content=content,
                    source=source,
                    metadata=metadata,
                )
            )
        return documents

    def _document_frequency(self) -> Counter[str]:
        frequencies: Counter[str] = Counter()
        for tokens in self.document_tokens:
            frequencies.update(tokens.keys())
        return frequencies

    @staticmethod
    def _search_text(document: KnowledgeHit) -> str:
        metadata_text = " ".join(f"{key} {value}" for key, value in document.metadata.items())
        return f"{document.title} {metadata_text} {document.content}"

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        text = text.lower()
        tokens = re.findall(r"[a-z0-9.]+", text)
        for sequence in re.findall(r"[\u4e00-\u9fff]+", text):
            tokens.extend(sequence)
            if len(sequence) > 1:
                tokens.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))
        return tokens

