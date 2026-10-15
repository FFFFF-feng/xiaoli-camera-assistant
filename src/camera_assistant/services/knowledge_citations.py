"""Bounded, offline citation audit of quoted principles, never free-form entailment."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from camera_assistant.knowledge.retriever import ManagedKnowledgeRetriever
from camera_assistant.knowledge_citation_models import (
    KnowledgeCitation,
    KnowledgeCitationReview,
    ReviewedKnowledgeCitation,
)


def _json(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def citation_candidates(raw: Any) -> list[KnowledgeCitation | dict]:
    """Isolate optional malformed references without rejecting unrelated parameters."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return [{"citation_error": "malformed_citation_list"}]
    results: list[KnowledgeCitation | dict] = []
    for value in raw[:100]:
        try:
            results.append(KnowledgeCitation.model_validate(value))
        except (ValidationError, TypeError, ValueError):
            results.append({"citation_error": "malformed_citation"})
    if len(raw) > 100:
        results.append({"citation_error": "citation_limit_exceeded"})
    return results


def knowledge_evidence_text(hits: list) -> str:
    """All source identifiers and conditions go into the actual model request."""
    materials = []
    for hit in hits:
        metadata = hit.metadata
        version = metadata.get("version", "")
        materials.append({
            "document_id": hit.document_id,
            "version": int(version) if version.isdigit() else "unversioned",
            "title": hit.title,
            "body": metadata.get("body", hit.content),
            "source": {
                "name": hit.source,
                "url": metadata.get("source_url", ""),
                "location": metadata.get("source_location", ""),
                "license": metadata.get("source_license", ""),
            },
            "conditions": _json(metadata.get("conditions", "{}"), {}),
            "applicability_requires": _json(metadata.get("requires", "[]"), []),
            "usage_scope": metadata.get("usage_scope", "unreviewed_legacy"),
            "numeric_defaults": _json(metadata.get("numeric_defaults", "null"), None),
            "content_hash": metadata.get("content_hash", ""),
        })
    return json.dumps(materials, ensure_ascii=False, separators=(",", ":"))


def model_output_schema(schema: dict) -> dict:
    """Omit program-derived review state and unreachable definitions from prompts."""
    schema = json.loads(json.dumps(schema))
    excluded = {"validation_notes", "safety_notes", "reviewed_operations", "exposure_state"}
    schema["properties"] = {key: value for key, value in schema.get("properties", {}).items()
                            if key not in excluded}
    schema["required"] = [key for key in schema.get("required", []) if key not in excluded]
    definitions = schema.pop("$defs", {})
    used = {}

    def visit(value):
        if isinstance(value, dict):
            ref = value.get("$ref", "")
            if ref.startswith("#/$defs/"):
                name = ref.rsplit("/", 1)[-1]
                if name not in used and name in definitions:
                    used[name] = definitions[name]
                    visit(definitions[name])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    if used:
        schema["$defs"] = used
    return schema


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, Mapping) else getattr(obj, key, default)


def _claim_text(obj: Any, path: str) -> Any:
    # Claims are separate principle lines. Parameter fields never acquire source support.
    if not re.fullmatch(r"(?:reasons|risks|adjustments)\.\d+", path):
        return None
    name, index = path.split(".")
    items = _get(obj, name, [])
    return items[int(index)] if int(index) < len(items) else None


def _principle_sentences(body: str) -> set[str]:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith((
        "【", "适用", "项目边界", "来源", "结构化资料", "#", "条件", "署名",
    ))]
    sentences = set()
    for line in lines:
        for match in re.finditer(r"[^。！？\n]+[。！？]?", line):
            sentence = match.group(0).strip()
            if len(sentence) >= 8:
                sentences.add(sentence)
    return sentences


def _complete_principle_span(claim: str, body: str) -> bool:
    sentences = [match.group(0).strip() for match in re.finditer(r"[^。！？\n]+[。！？]?", claim)]
    allowed = _principle_sentences(body)
    return bool(sentences) and claim in body and all(sentence in allowed for sentence in sentences)


def review_knowledge_citations(
    recommendation: Any, hits: list, conditions: Mapping[str, Any] | None = None,
) -> KnowledgeCitationReview:
    """Accept only a standalone verbatim principle bound to the final advice text.

    Matching an ID or an excerpt alone never establishes entailment. Arbitrary
    paraphrases, numeric recommendations, site facts and geometry are unreviewed.
    """
    report = KnowledgeCitationReview(notes=[
        "引用审核只核对本次资料中的独立通用原则原句；不证明具体参数、现场照度、几何效果或建议正确率。",
        "机器条件匹配不代表资料文字前提已在现场满足；这些前提仍需用户检查。",
    ])
    by_id = {hit.document_id: hit for hit in hits}
    raw = _get(recommendation, "knowledge_citations", [])
    for value in citation_candidates(raw):
        if not isinstance(value, KnowledgeCitation):
            report.rejected.append(ReviewedKnowledgeCitation(reason=value["citation_error"]))
            continue
        checked = ReviewedKnowledgeCitation(citation=value, reason="")
        hit = by_id.get(value.document_id)
        if hit is None:
            checked.reason = "document_not_in_request"
        else:
            checked.title, checked.source = hit.title, hit.source
            checked.source_url = hit.metadata.get("source_url", "")
            checked.source_license = hit.metadata.get("source_license", "")
            declared_conditions = _json(hit.metadata.get("conditions"), None)
            checked.conditions = declared_conditions if isinstance(declared_conditions, dict) else {}
            requires = _json(hit.metadata.get("requires", "[]"), [])
            checked.applicability_requires = (
                requires if isinstance(requires, list) and all(isinstance(item, str)
                                                             for item in requires) else []
            )
            checked.usage_scope = hit.metadata.get("usage_scope", "unknown")
            body = hit.metadata.get("body", hit.content)
            version = str(value.version)
            if (hit.metadata.get("version") != version
                    or not value.document_id.endswith(f"@v{value.version}")):
                checked.reason = "version_not_in_request"
            elif not isinstance(declared_conditions, dict):
                checked.reason = "conditions_not_declared_or_invalid"
            elif not ManagedKnowledgeRetriever._applicable(
                checked.conditions, conditions,
            ):
                checked.reason = "conditions_not_met"
            elif value.source_excerpt not in body:
                checked.reason = "source_excerpt_not_found"
            elif _claim_text(recommendation, value.claim_path) != value.claim:
                checked.reason = "final_claim_changed_or_unsupported_path"
            elif value.claim != value.source_excerpt or not _complete_principle_span(value.claim, body):
                checked.reason = "claim_not_standalone_source_principle"
            elif re.search(r"\d|照度|勒克斯|lux|保证|必定|眼镜|镜片|旋转|侧移|俯仰", value.claim,
                           re.IGNORECASE):
                checked.reason = "numeric_scene_or_geometry_not_supported"
            else:
                checked.reason = "exact_source_principle_bound_to_final_text"
                checked.support_scope = "quoted_general_principle"
        if checked.support_scope == "quoted_general_principle":
            report.accepted.append(checked)
        else:
            report.rejected.append(checked)
    if not raw:
        report.notes.append("本次输出没有可审核的知识引用；命中或注入资料不等于已引用。")
    return report
