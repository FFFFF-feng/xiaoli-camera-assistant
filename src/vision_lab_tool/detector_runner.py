"""One VLM answer shared by A/B1/B2; detector stages fail independently."""
from __future__ import annotations

import hashlib
import inspect
import json
import time
from pathlib import Path
from string import Formatter
from uuid import uuid4

import httpx
from pydantic import Field, model_validator

from vision_lab_tool import detector_queries as query_module
from vision_lab_tool import detector_scope as scope_module
from vision_lab_tool.adapters import build_request, parse_response
from vision_lab_tool.detector_mock import detect_mock, vlm_payload
from vision_lab_tool.detector_models import (
    DetectionObject,
    DetectionResult,
    DetectorConfig,
    DetectorExperiment,
    MethodResult,
    SemanticObject,
    SubjectSelection,
    VLMSnapshot,
)
from vision_lab_tool.detector_queries import (
    COCO_CLASSES,
    canonical,
    compose_queries,
    english_queries,
    label_components,
)
from vision_lab_tool.evaluation import estimate_cost
from vision_lab_tool.models import ModelConfig, StrictModel, validate_box
from vision_lab_tool.security import scrub

BASELINE_PROMPT_VERSION = "localization-prompt-v1"
CANDIDATE_PROMPT_VERSION = "localization-prompt-v2"
SCOPE_PROMPT_VERSION = "localization-prompt-v3"
PROMPT_VERSION = BASELINE_PROMPT_VERSION
ASSOCIATION_RULE_VERSION = "conservative-association-v4"
# The historical localization-prompt-v1 is the iteration experiment's frozen v0.
# Keep its exact wording available when a later candidate is registered.
LOCALIZATION_PROMPT_TEMPLATES = {
    BASELINE_PROMPT_VERSION: (
        "只完成摄影目标定位，不给拍摄建议。共同用户任务：\n{task}\n"
        "识别可见对象，输出严格JSON，不执行数学表达式、不猜坐标单位。"
        "bbox为发送JPEG对应方向修正图的0到1 xyxy；无合法框用null。"
        "query必须是简短英文类别短语，label可用中文。区分whole/part/instance/region/"
        "combination/unknown。没有证据的实体归属用unknown；其余允许physical/reflection/"
        "depiction/mannequin/scale_model。局部不能冒充整体。"
        "任务不足以唯一确定主体时subject_status=ambiguous或abstained，main_subject_ids=[]。"
        "一个对象一个ID，父对象ID必须存在。仅输出符合以下schema的JSON：\n{schema}"
    ),
    CANDIDATE_PROMPT_VERSION: (
        "只完成摄影目标定位，不给拍摄建议。共同用户任务：\n{task}\n"
        "识别可见对象，输出一个严格JSON结果实例，不输出JSON Schema，也不输出Markdown。"
        "结果根对象只能包含objects、main_subject_ids、subject_status这三个字段。"
        "绝不在结果中输出$defs、properties、type、required、title、additionalProperties等"
        "schema元数据；下面的schema只是字段校验契约，不是需要复制的回答。\n"
        "bbox只接受发送JPEG对应方向修正图的0到1归一化xyxy，即"
        "[横向起点,纵向起点,横向终点,纵向终点]，四个值必须为0到1之间的十进制有限数，"
        "横向起点小于横向终点、纵向起点小于纵向终点。禁止0到1000坐标、像素坐标、"
        "百分数字符串、分数、数学表达式、NaN或Infinity。不猜坐标单位；无法可靠给出"
        "合法可见框时bbox用null。confidence用0到1有限数或null。\n"
        "query必须是简短英文类别短语，label可用中文。区分whole/part/instance/region/"
        "combination/unknown。没有证据的实体归属用unknown；其余允许physical/reflection/"
        "depiction/mannequin/scale_model，按可见证据填写，不要求一律unknown。局部不能冒充整体。"
        "subject_status只允许selected、ambiguous、abstained，不能使用clear或其他枚举。"
        "selected时main_subject_ids必须非空、无重复且每个ID引用objects中存在的对象；"
        "ambiguous或abstained时main_subject_ids必须为空数组。"
        "任务不足以唯一确定主体时subject_status=ambiguous或abstained，main_subject_ids=[]。"
        "一个对象一个ID，父对象ID必须存在。\n"
        "以下仅示意JSON实例的字段结构，不代表当前图片的对象类别、数量、实体状态或框，"
        "示例bbox数值仅说明十进制归一化单位，绝不能当作当前图的答案。"
        "不能复制示例类别、数量或坐标；有可靠可见范围才填实际数值，否则null。"
        "请根据图片和任务填值：\n"
        '{{"objects":[{{"object_id":"example_id","label":"示意对象","query":"object",'
        '"target_level":"unknown","entity_kind":"unknown","parent_object_id":null,'
        '"bbox":[0.12,0.23,0.45,0.67],"confidence":null}}],'
        '"main_subject_ids":[],"subject_status":"abstained"}}\n'
        "字段校验schema（仅用于理解约束，不要输出它）：\n{schema}\n"
        "最终回答只能是上述三个根字段的JSON实例；bbox采用0到1的有限数，"
        "不包含schema元数据。"
    ),
}
# Scope is the second development factor. The complete first candidate stays
# byte-for-byte available; all non-prompt validation and matching rules are shared.
LOCALIZATION_PROMPT_TEMPLATES[SCOPE_PROMPT_VERSION] = (
    LOCALIZATION_PROMPT_TEMPLATES[CANDIDATE_PROMPT_VERSION]
    + "\n任务范围与层级补充（保持以上JSON实例和坐标契约）："
    "生成最终JSON前，先在内部按共同任务核对所有可见的必需目标单元，核对过程不要输出。"
    "任务包含多个可见目标时，不能只保留最显著的一项，也不能通过减少目标避免格式错误。"
    "任务同时要求整体和部件时，两者必须分别出现在objects中，各用独立object_id和"
    "各自可见范围的bbox；已识别的部件通过parent_object_id引用存在的整体ID，"
    "不能把一个局部框标成whole，也不能用整体框代替部件。"
    "whole的紧致外接框必须包括属于同一整体的全部可见构成，含细小或伸至图像边缘的"
    "可见部分；截断对象仅框图内可见范围，不外推画外或被遮挡部位。"
    "左右对象和同类不同实例各用独立ID与框，不合并成一个对象或共用ID。"
    "自然区域或对象内部区域用target_level=region，按该区域自身范围给框，"
    "不拿包含它的整个对象代替内部区域。"
    "明确指定的多个目标可以同时成为主体：subject_status=selected时，"
    "main_subject_ids可并列引用任务明确要求的多个主目标ID，不要求仅有一个对象；"
    "唯一性针对任务所指定的目标集合。任务未指定可确定的主角或目标集合时仍保留"
    "ambiguous，不任选一个显著、最大或高置信度对象。"
    "可见范围未知或不可稳定划界时保留bbox=null，不捏造框或补全不可见部位；"
    "不可确认存在的对象不捏造。entity_kind仍只按可见证据判断，不要求一律unknown。"
    "最后只输出符合上述三个根字段的JSON实例。"
)


class VLMObject(SemanticObject):
    bbox: list[float] | None
    confidence: float | None = Field(ge=0, le=1)

    @model_validator(mode="after")
    def valid_box(self):
        if self.bbox is not None:
            validate_box(self.bbox)
        return self


class VLMPayload(StrictModel):
    objects: list[VLMObject]
    main_subject_ids: list[str]
    subject_status: str

    @model_validator(mode="after")
    def binding(self):
        ids = [v.object_id for v in self.objects]
        if len(ids) != len(set(ids)):
            raise ValueError("VLM object_id 重复")
        if len(self.main_subject_ids) != len(set(self.main_subject_ids)):
            raise ValueError("VLM selected IDs 重复")
        if any(v not in ids for v in self.main_subject_ids):
            raise ValueError("VLM 主体引用不存在")
        if any(v.parent_object_id and v.parent_object_id not in ids for v in self.objects):
            raise ValueError("VLM parent_object_id 不存在")
        if self.subject_status not in {"selected", "ambiguous", "abstained"}:
            raise ValueError("VLM subject_status 不合法")
        if (self.subject_status == "selected") != bool(self.main_subject_ids):
            raise ValueError("VLM 主体选择状态与ID不一致")
        return self


def register_localization_prompt(version, template):
    """Restore a frozen template, or register a separately named candidate.

    JSON examples in templates must escape literal braces as {{ and }}. The
    only substitutions are the common task and the actual validation schema.
    An existing version is immutable; a wording change requires a new name.
    """
    fields = [(field, spec, conversion) for _, field, spec, conversion
              in Formatter().parse(template) if field is not None]
    if (not version or {field for field, _, _ in fields} != {"task", "schema"}
            or any(spec or conversion for _, spec, conversion in fields)):
        raise ValueError("定位模板必须仅包含task和schema占位符")
    if version in LOCALIZATION_PROMPT_TEMPLATES and LOCALIZATION_PROMPT_TEMPLATES[version] != template:
        raise ValueError("定位提示词版本已存在且内容不同；使用新版本")
    LOCALIZATION_PROMPT_TEMPLATES[version] = template


def localization_prompt(task, prompt_version=None, *, schema=None):
    version = prompt_version or PROMPT_VERSION
    if version not in LOCALIZATION_PROMPT_TEMPLATES:
        raise ValueError("未知定位提示词版本：" + version)
    schema = VLMPayload.model_json_schema() if schema is None else schema
    return LOCALIZATION_PROMPT_TEMPLATES[version].format(
        task=task, schema=json.dumps(schema, ensure_ascii=False))


def _text_sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_sha256(value):
    return _text_sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def localization_provenance(task, prompt_version=None):
    """Capture exact sending inputs and executable vocabulary/association rules."""
    version = prompt_version or PROMPT_VERSION
    schema = VLMPayload.model_json_schema()
    schema_json = json.dumps(schema, ensure_ascii=False)
    prompt = localization_prompt(task, version, schema=schema)
    dictionary = {
        "task_dictionary": dict(query_module.TASK_DICTIONARY),
        "aliases": dict(query_module.ALIASES),
        "coco_classes": list(query_module.COCO_CLASSES),
        "association_coco_classes": list(COCO_CLASSES),
        "implementation": {name: inspect.getsource(getattr(query_module, name))
                           for name in ("canonical", "english_queries", "task_queries", "compose_queries",
                                        "label_components")},
    }
    association_rules = inspect.getsource(_associate) + "\n" + inspect.getsource(scope_module)
    return {
        "provenance_version": "localization-provenance-v1",
        "localization_prompt_version": version,
        "localization_prompt_template": LOCALIZATION_PROMPT_TEMPLATES[version],
        "localization_prompt": prompt,
        "localization_prompt_sha256": _text_sha256(prompt),
        "result_schema": schema,
        "result_schema_json": schema_json,
        "result_schema_sha256": _text_sha256(schema_json),
        "dictionary_version": query_module.DICTIONARY_VERSION,
        "dictionary": dictionary,
        "dictionary_sha256": _json_sha256(dictionary),
        "association_rule_version": ASSOCIATION_RULE_VERSION,
        "association_rules": association_rules,
        "association_rule_sha256": _text_sha256(association_rules),
    }


def _no_duplicate_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("JSON重复键")
        obj[key] = value
    return obj


def parse_snapshot(snapshot):
    """Independent semantic validation never repairs A's illegal boxes."""
    text = snapshot.raw_answer.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.partition("\n")[2].rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(text, object_pairs_hook=_no_duplicate_keys)
        if not isinstance(payload, dict):
            raise TypeError("根必须为对象")
        snapshot.parsed = payload
        snapshot.json_status = "success"
    except (ValueError, TypeError):
        snapshot.status = snapshot.json_status = "json_error"
        snapshot.box_status = snapshot.semantic_status = "not_available"
        return snapshot
    try:
        objects = payload["objects"]
        if not isinstance(objects, list) or not objects:
            raise ValueError("语义对象列表为空")
        semantics = [SemanticObject.model_validate({k: v for k, v in obj.items()
                     if k not in {"bbox", "confidence"}}) for obj in objects]
        ids = [v.object_id for v in semantics]
        if len(ids) != len(set(ids)):
            raise ValueError("语义ID重复")
        english_queries([v.query for v in semantics])
        if any(v.parent_object_id and v.parent_object_id not in ids for v in semantics):
            raise ValueError("语义父ID不存在")
        snapshot.semantics = semantics
        snapshot.semantic_status = "success"
        mains = payload.get("main_subject_ids", [])
        state = payload.get("subject_status")
        if (isinstance(mains, list) and all(isinstance(v, str) and v in ids for v in mains)
            and len(set(mains)) == len(mains)
            and state in {"selected", "ambiguous", "abstained"}
            and (state == "selected") == bool(mains)):
            snapshot.main_subject_ids = mains
            snapshot.subject_status = state
            snapshot.selection_status = "success"
        else:
            snapshot.selection_status = "selection_format_error"
    except (KeyError, ValueError, TypeError, AttributeError):
        snapshot.semantic_status = "semantic_error"
    try:
        validated = VLMPayload.model_validate(payload)
        snapshot.main_subject_ids = validated.main_subject_ids
        for obj in validated.objects:
            if obj.bbox is not None:
                snapshot.candidates.append(DetectionObject(
                    object_id=obj.object_id, label_original=obj.query, label_display=obj.label,
                    score=obj.confidence, score_kind="vlm_self_reported_confidence",
                    bbox_native=obj.bbox, bbox_postprocessed=obj.bbox, bbox=obj.bbox,
                    coordinate_basis="VLM declared normalized xyxy; validated without conversion",
                    target_level=obj.target_level, entity_kind=obj.entity_kind,
                    parent_object_id=obj.parent_object_id, semantic_source="shared_vlm",
                ))
        # A selected object without a box is a box failure, not a selected success.
        boxed = {o.object_id for o in snapshot.candidates}
        if any(v not in boxed for v in validated.main_subject_ids):
            snapshot.box_status = "missing_box"
        else:
            snapshot.box_status = "success" if boxed else "empty"
    except (ValueError, TypeError):
        snapshot.box_status = "box_format_error"
        snapshot.candidates = []
    snapshot.status = "success" if snapshot.box_status == "success" else snapshot.box_status
    return snapshot


def invoke_localization(config, task, image, key="", simulated=False, case="valid", transport=None,
                        prompt_version=None):
    started = time.perf_counter()
    provenance = localization_provenance(task, prompt_version)
    snapshot = VLMSnapshot(config=config, real=not simulated and config.protocol != "mock",
                           provenance=provenance)
    attempt = {"attempt_id": uuid4().hex, "status": "started",
               "prompt_version": provenance["localization_prompt_version"],
               "prompt_sha256": provenance["localization_prompt_sha256"],
               "schema_sha256": provenance["result_schema_sha256"], "request_sent": False}
    secrets = [key, image.data_url, image.data_url.partition(",")[2]]
    try:
        if simulated or config.protocol == "mock":
            if case == "vlm_network" or config.mock_case == "failure":
                snapshot.status = "network_error"
                snapshot.error = "模拟网络失败；未请求真实服务"
                return snapshot
            snapshot.raw_answer = "invalid JSON" if case == "vlm_json" else json.dumps(
                vlm_payload(case), ensure_ascii=False)
        else:
            prompt = provenance["localization_prompt"]
            url, headers, body = build_request(config, prompt, image.data_url, "recognition", key,
                                               schema_override=provenance["result_schema"])
            with httpx.Client(timeout=config.timeout, transport=transport) as client:
                attempt["request_sent"] = True
                response = client.post(url, headers=headers, json=body)
            attempt["response_status"] = response.status_code
            if response.status_code >= 400:
                # Redact before truncation so a limit cannot leave a partial key.
                error_bytes = scrub(response.text, secrets).encode("utf-8")
                attempt["response_error_body"] = error_bytes[:16384].decode(
                    "utf-8", errors="replace")
                attempt["response_error_body_truncated"] = len(error_bytes) > 16384
                attempt["response_error_body_limit_bytes"] = 16384
                snapshot.status = "authentication" if response.status_code in {401, 403} else "http_error"
                snapshot.error = f"HTTP {response.status_code}；一次尝试，未重试"
                return snapshot
            reply = parse_response(config.protocol, response.json())
            snapshot.raw_answer = scrub(reply.text, secrets)
            snapshot.actual_model = scrub(reply.model, secrets)
            snapshot.usage = reply.usage.model_validate(scrub(reply.usage.model_dump(), secrets))
            snapshot.cost = estimate_cost(reply.usage, config.price)
            if reply.truncated or reply.refused:
                snapshot.status = "truncated" if reply.truncated else "refused"
                return snapshot
        parse_snapshot(snapshot)
    except httpx.TimeoutException:
        snapshot.status, snapshot.error = "timeout", "VLM超时；未重试，费用未知"
    except httpx.RequestError:
        snapshot.status, snapshot.error = "network_error", "VLM网络失败；未重试，费用未知"
    except (ValueError, TypeError, KeyError):
        snapshot.status, snapshot.error = "response_error", "响应/配置不合法；未重试"
    except Exception as exc:  # noqa: BLE001 -- failure isolation, never expose service traceback
        snapshot.status, snapshot.error = "runtime_error", type(exc).__name__
    finally:
        snapshot.elapsed_seconds = time.perf_counter() - started
        attempt.update(status=snapshot.status, elapsed_seconds=snapshot.elapsed_seconds)
        snapshot.attempts.append(attempt)
    return VLMSnapshot.model_validate(scrub(snapshot.model_dump(mode="json"), secrets))


def _fingerprint(config):
    data = config.model_dump(mode="json")
    if "weights_path" in data:
        path = Path(data["weights_path"]) if data["weights_path"] else (
            Path(__file__).resolve().parents[2] / "data/vision_lab/model_cache" /
            ("grounding-dino-tiny" if data["detector"] == "grounding_dino" else "yolo26n.pt")
        )
        if path.is_file():
            stat = path.stat()
            data["weight_stat"] = [stat.st_size, stat.st_mtime_ns]
        elif path.is_dir():
            data["weight_stat"] = [(p.name, p.stat().st_size, p.stat().st_mtime_ns)
                                   for p in sorted(path.rglob("*")) if p.is_file()]
        runtime_path = Path(__file__).resolve().parents[2] / "data/vision_lab/model_cache/runtime.json"
        if runtime_path.is_file():
            data["runtime_sha256"] = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    return data


def _cache_key(kind, image, task, config, extras, provenance=None):
    # Simulated fixtures do not load weights; their cache is independent of the
    # concurrently prepared public model files. Empty paths never mean project root.
    fixture = kind == "detector" and extras[1]
    provenance = localization_provenance(task) if provenance is None else provenance
    return hashlib.sha256(json.dumps({
        "kind": kind, "sent": image.metadata(), "task": task,
        "config": config.model_dump(mode="json") if fixture else _fingerprint(config),
        "extras": extras,
        "provenance": {key: provenance[key] for key in (
            "provenance_version", "localization_prompt_version", "localization_prompt_sha256",
            "result_schema_sha256", "dictionary_version", "dictionary_sha256",
            "association_rule_version", "association_rule_sha256")},
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _a_method(snapshot):
    selected = snapshot.main_subject_ids if snapshot.box_status == "success" else []
    status = snapshot.status
    selection_status = "selected" if selected else (
        snapshot.subject_status if snapshot.box_status == "success"
        and snapshot.subject_status in {"ambiguous", "abstained"} else "abstained")
    return MethodResult(method="A", status=status, candidates=snapshot.candidates,
                        selection=SubjectSelection(status=selection_status, selected_ids=selected,
                            candidate_ids=[v.object_id for v in snapshot.candidates],
                            reason="共享VLM直接输出，未经检测器修复"),
                        stages={"vlm": snapshot.status, "json": snapshot.json_status,
                                "boxes": snapshot.box_status, "semantics": snapshot.semantic_status,
                                "subject_format": snapshot.selection_status},
                        timings={"vlm": snapshot.elapsed_seconds}, real=snapshot.real)


def _associate(detection, snapshot, queries, method):
    objects = [v.model_copy(deep=True) for v in detection.filtered_candidates]
    associations = []
    selected = []
    matched_main_ids = set()
    unsupported = []
    reliable = snapshot is not None and snapshot.semantic_status == "success"
    semantics = snapshot.semantics if reliable else []
    queries = dict(queries)
    scope = scope_module.resolve_task_scope(queries.get("task_text", ""), semantics,
                                           snapshot.main_subject_ids if snapshot else [])
    queries["task_scope"] = scope
    roles = {r["object_id"]: r for r in scope["object_roles"]}
    normalized = {o.object_id: label_components(o.label_original, queries.get("merged", []))
                  for o in objects}
    queries["label_normalization"] = normalized
    semantic_matches = {}
    uses = {}
    for sem in semantics:
        query = canonical(sem.query)
        matches = [o for o in objects if query in normalized[o.object_id]["components"]
                   and scope_module.level_compatible(o, sem, detection.config.detector,
                                                       normalized[o.object_id]["components"])]
        semantic_matches[sem.object_id] = matches
        if len(matches) == 1:
            uses.setdefault(matches[0].object_id, []).append(sem.object_id)
    for sem in semantics:
        query = canonical(sem.query)
        role = roles[sem.object_id]
        if detection.config.detector == "yolo26" and (
                query not in COCO_CLASSES or sem.target_level not in {"whole", "instance"}):
            if role["required"]:
                unsupported.append(sem.object_id + ":" + query)
            associations.append({"vlm_object_id": sem.object_id, "query": query,
                                 "query_original": sem.query, "scope_role": role["role"],
                                 "scope_evidence": role["evidence"],
                                 "candidate_ids": [], "status": "unsupported"})
            continue
        matches = semantic_matches[sem.object_id]
        associations.append({"vlm_object_id": sem.object_id, "query": query,
                             "query_original": sem.query, "scope_role": role["role"],
                             "scope_evidence": role["evidence"],
                             "candidate_ids": [o.object_id for o in matches],
                             "status": "unique_class" if len(matches) == 1 else "ambiguous_or_missing",
                             "basis": "complete query phrases + frozen aliases; no score/area/GT matching"})
        # Grounding phrase defines its target level; YOLO whole-person semantics can
        # describe the detected person but no parts/regions/combination are substituted.
        if len(matches) == 1:
            obj = matches[0]
            if len(uses[obj.object_id]) != 1:
                associations[-1]["status"] = "ambiguous_shared_candidate"
                continue
            if detection.config.detector == "yolo26" and sem.target_level not in {"whole", "instance"}:
                associations[-1]["status"] = "level_mismatch"
                continue
            obj.target_level = sem.target_level
            obj.semantic_source = "shared_vlm+exact_category_association"
            # Reflection/depiction identity cannot be proved by category agreement.
            if sem.object_id in snapshot.main_subject_ids and sem.entity_kind == "unknown":
                selected.append(obj.object_id)
                matched_main_ids.add(sem.object_id)
    task_unsupported = [u["query"] for u in scope["required_units"]
                        if u.get("support_status") != "unknown" and (u["query"] not in COCO_CLASSES
                        or u["target_level"] not in {"category", "whole", "instance"})]
    if detection.config.detector == "yolo26":
        unsupported.extend(task_unsupported)
    ids = [o.object_id for o in objects]
    candidate_ok = detection.status in {"success", "ok", "partial_coordinates"}
    required_ids = {r["object_id"] for r in scope["object_roles"] if r["required"]}
    covered_ids = {a["vlm_object_id"] for a in associations if a["status"] == "unique_class"}
    required_missing = bool(scope["missing_semantic_units"] or required_ids - covered_ids)
    if not candidate_ok:
        state, reason = "abstained", "检测阶段未提供合法完整输出"
        selected = []
    elif not reliable and method != "detector_only":
        state, reason = "detection_only", "VLM语义失败：保留本地候选，完整联合主体选择弃权"
        selected = []
    elif unsupported:
        state, reason = "unsupported", "固定类别不能覆盖所有任务目标"
        selected = []
    elif method == "detector_only":
        state, reason = "abstained", "纯检测仅提供候选；人工选择另记辅助条件"
        selected = []
    elif scope["status"] != "known" or required_missing:
        state, reason = "ambiguous", "任务必需单元尚缺可靠范围/完整候选；不以主体ID缩小任务"
        selected = []
    elif any(len(values) > 1 for values in uses.values()):
        state, reason = "ambiguous", "多个语义对象引用同一候选；禁止实例/层级复用"
        selected = []
    elif (snapshot.selection_status == "success" and snapshot.subject_status == "selected"
          and snapshot.main_subject_ids and matched_main_ids == set(snapshot.main_subject_ids)
          and len(set(selected)) == len(selected)):
        state, reason = "selected", "每个VLM主目标仅有一个类别兼容候选；实体归属unknown"
    else:
        state, reason = "ambiguous" if objects else "abstained", "无可靠唯一关联，不按分数或面积强选"
        selected = []
    return MethodResult(method=method, detector=detection.config.detector,
                        status="detection_only" if state == "detection_only" else detection.status,
                        candidates=objects, detection=detection, queries=queries,
                        unsupported_targets=unsupported,
                        selection=SubjectSelection(status=state, selected_ids=selected,
                            rule_version=ASSOCIATION_RULE_VERSION,
                            candidate_ids=ids, reason=reason, associations=associations),
                        stages={"detector": detection.status,
                                "semantics": snapshot.semantic_status if snapshot else "not_applicable",
                                "selection": state}, timings=detection.timings.copy(),
                        real=detection.real and (snapshot.real if snapshot else True))


def associate_detection(detection, snapshot, queries):
    """Use the same conservative B2 association in the app and the experiment tool."""
    return _associate(detection, snapshot, queries, "B2")


def run_experiment(image, configs, mode, task_prompt, vlm_config=None, key="",
                   experiment_version="detector-v1", dataset_split="开发", manual_queries=None,
                   simulated=False, mock_case="valid", cache=None, on_stage=None,
                   cancel_event=None, transport=None, detect_fn=None, prompt_version=None):
    # Streamlit hot reload may leave previous-generation Pydantic instances in
    # session state. Rehydrate frozen values without changing their content.
    configs = [DetectorConfig.model_validate(c.model_dump(mode="json")) for c in configs]
    if vlm_config is not None:
        vlm_config = ModelConfig.model_validate(vlm_config.model_dump(mode="json"))
    if mode not in {"pure_detection", "localization"}:
        raise ValueError("未知检测实验模式")
    if not configs or len({v.detector for v in configs}) != len(configs):
        raise ValueError("选择至少一个独立检测器")
    if mode == "localization" and vlm_config is None:
        raise ValueError("定位对照需要一个VLM配置")
    if mode == "localization" and manual_queries:
        raise ValueError("主对照不允许人工补词；请在纯检测另作诊断")
    cache = {} if cache is None else cache
    provenance = localization_provenance(task_prompt, prompt_version)
    started = time.perf_counter()
    run = DetectorExperiment(mode=mode, experiment_version=experiment_version,
            dataset_split=dataset_split, task_prompt=task_prompt,
            task_prompt_sha256=hashlib.sha256(task_prompt.encode()).hexdigest(),
            image=image.metadata(), configs=[c.model_copy(deep=True) for c in configs],
            dictionary_version=provenance["dictionary_version"], provenance=provenance,
            simulated=simulated or bool(mode == "localization" and vlm_config.protocol == "mock"),
            stages={"run": "running"})
    # Planned method identities exist before any request. Interrupted/unexecuted
    # stages remain visible in history and never vanish from operational denominators.
    if mode == "localization":
        run.vlm = VLMSnapshot(config=vlm_config, status="pending",
                              provenance=provenance,
                              real=not simulated and vlm_config.protocol != "mock")
        run.results.append(MethodResult(method="A", real=run.vlm.real))
    for config in configs:
        run.results.append(MethodResult(method="detector_only" if mode == "pure_detection" else
            "B1" if config.detector == "grounding_dino" else "B2", detector=config.detector,
            real=not simulated, stages={"detector": "pending"}))

    def emit():
        run.timings["total"] = time.perf_counter() - started
        if on_stage:
            on_stage(run.model_copy(deep=True))

    def cancelled():
        return cancel_event is not None and cancel_event.is_set()

    emit()
    if mode == "localization":
        run.stages["vlm"] = "running"
        emit()
        ck = _cache_key("vlm", image, task_prompt, vlm_config, [simulated, mock_case], provenance)
        if cancelled():
            run.vlm = VLMSnapshot(config=vlm_config, status="cancelled",
                                  provenance=provenance,
                                  real=not simulated and vlm_config.protocol != "mock")
        elif ck in cache:
            run.vlm = VLMSnapshot.model_validate(cache[ck].model_dump(mode="json"))
            source = run.vlm.result_id
            run.vlm.result_id = uuid4().hex
            run.vlm.cache_hit, run.vlm.cache_source = True, source
        else:
            run.vlm = invoke_localization(vlm_config, task_prompt, image, key, simulated,
                                          mock_case, transport, prompt_version=prompt_version)
            cache[ck] = run.vlm.model_copy(deep=True)
        run.stages["vlm"] = run.vlm.status
        direct = _a_method(run.vlm)
        direct.result_id = run.results[0].result_id
        run.results[0] = direct
        emit()
    query_started = time.perf_counter()
    queries = compose_queries(task_prompt, run.vlm.semantics if run.vlm else (), manual_queries or [])
    run.timings["query_conversion"] = time.perf_counter() - query_started
    if run.vlm and run.vlm.semantic_status != "success":
        queries["fallback_trigger"] = run.vlm.status
    for config_index, config in enumerate(configs):
        method = "detector_only" if mode == "pure_detection" else (
            "B1" if config.detector == "grounding_dino" else "B2")
        run.stages[config.detector] = "running"
        emit()
        qs = queries["merged"] if config.detector == "grounding_dino" else []
        ck = _cache_key("detector", image, task_prompt, config, [qs, simulated, mock_case], provenance)
        if cancelled():
            result = DetectionResult(config=config, status="cancelled", real=not simulated)
        elif ck in cache:
            result = DetectionResult.model_validate(cache[ck].model_dump(mode="json"))
            result.cache_source, result.result_id = result.result_id, uuid4().hex
            result.cache_hit = True
        else:
            try:
                if simulated:
                    result = detect_mock(image, qs, config, mock_case)
                else:
                    if detect_fn is None:
                        from vision_lab_tool.detectors.client import detect
                        detect_fn = detect
                    result = detect_fn(image, qs, config)
                if result.status in {"success", "ok", "empty", "partial_coordinates"}:
                    cache[ck] = result.model_copy(deep=True)
            except Exception as exc:  # noqa: BLE001 -- preserve A and other independent detector
                result = DetectionResult(config=config, status="runtime_error", real=not simulated,
                    diagnostics=["独立检测阶段失败：" + type(exc).__name__])
        selection_started = time.perf_counter()
        derived = _associate(result, run.vlm, queries.copy(), method)
        derived.timings["selection"] = time.perf_counter() - selection_started
        derived.timings["query_conversion"] = run.timings["query_conversion"]
        if run.vlm:
            derived.timings["shared_vlm"] = run.vlm.elapsed_seconds
        result_index = config_index + (1 if mode == "localization" else 0)
        derived.result_id = run.results[result_index].result_id
        run.results[result_index] = derived
        run.stages[config.detector] = result.status
        emit()
    run.stages["run"] = "cancelled" if cancelled() else "completed"
    run.costs = {
        "shared_vlm_call_count": 0 if run.vlm is None or run.vlm.cache_hit else len(run.vlm.attempts),
        "new_real_vlm_call_count": int(bool(run.vlm and run.vlm.real and not run.vlm.cache_hit
            and any(a.get("request_sent", False) for a in run.vlm.attempts))),
        "shared_vlm_cost": run.vlm.cost if run.vlm else None,
        "cost_source": run.vlm.cache_source if run.vlm and run.vlm.cache_hit else None,
        "local_cloud_fee": 0,
        "local_compute_cost": None,
        "note": "VLM共享一次；缓存来源的原费用不重复计账。本机计算成本未知。",
    }
    emit()
    return DetectorExperiment.model_validate(scrub(run.model_dump(mode="json"),
        [key, image.data_url, image.data_url.partition(",")[2]]))
