"""Production photography scope; the frozen detector experiment rules stay separate.

This bounded grammar distinguishes a requested subject from retention/background
instructions. Unknown requested nouns remain missing units, rather than allowing
the vision model's main IDs to silently narrow the user's request.
"""
from __future__ import annotations

import re

from vision_lab_tool.detector_queries import (
    ALIASES,
    COCO_CLASSES,
    TASK_DICTIONARY,
    canonical,
    english_queries,
)
from vision_lab_tool.detector_scope import COUNT_WORDS

SCOPE_RULE_VERSION = "production-photography-scope-v2"
PRODUCTION_DICTIONARY = {
    **TASK_DICTIONARY,
    "瀑布": "waterfall", "树林": "forest", "森林": "forest", "岩石": "rock",
    "瓶子": "bottle", "花朵": "flower",
}
_ACTION = (r"定位|找出|框出|识别|突出|重拍|重新拍摄|拍摄|拍|强调|聚焦|表现|捕捉|只保留|作为主体|"
           r"\b(?:locate|identify|detect|find|photograph|highlight|capture|focus)\b")
_GEOMETRY_ACTION = r"定位|找出|框出|识别|\b(?:locate|identify|detect|find)\b"
_AUXILIARY = (r"完整保留|(?<!只)保留|简化|忽略|无需定位|不定位|仅作背景|背景|上下文|尺度关系|"
              r"\b(?:preserve|retain|keep|ignore|background|context)\b")
_DETAIL = r"双眼|眼睛|耳朵|胡须|视线|头部|脚部|把手|杯柄|杯沿|杯底|徽标|杯口"
_ENTITY = (r"倒影|反射|镜子|镜中|画中|画里的|海报|卡通|模型|雕像|模特假人|"
           r"\b(?:reflection|reflected|depiction|depicted|mannequin|cartoon|"
           r"poster|painting|scale model)\b")
# Match the complete clause: named objects or extra qualifiers must not be
# swallowed merely because they share the words "reshoot" or "composition".
_OUTPUT_INSTRUCTION = (r"(?:请)?(?:(?:给出|提供)(?:重拍时|拍摄时)?"
                       r"(?:可以执行的|可执行的)?(?:构图调整|构图建议|重拍建议|拍摄建议)|"
                       r"(?:说明|解释)(?:曝光取舍|曝光调整|曝光建议))")
_NOISE = (r"请|分别|照片中|画面中|图中|可见|的|主体|整体|突出|重拍|重新拍摄|拍摄|拍|强调|聚焦|表现|"
          r"捕捉|定位|找出|框出|识别|只保留|以及|和|与|、|并|希望|用三脚架|三脚架|用|"
          r"也作为主体|作为主体|"
          r"所有|全部|(?:[一二两三四五六七八九十]|\d+)(?:个|只|位|枚|根|件|支)?|"
          r"\b(?:please|locate|identify|detect|find|photograph|highlight|capture|focus|"
          r"the|a|an|of|on|visible|whole|and|plus|one|two|three|four|five|six|seven|"
          r"eight|nine|ten|all|both)\b")


def _mentions(task, semantics):
    vocabulary = dict(PRODUCTION_DICTIONARY)
    vocabulary.update({q: canonical(q) for q in set(COCO_CLASSES) | set(ALIASES)
                       | set(PRODUCTION_DICTIONARY.values())})
    # English open-vocabulary categories must occur as complete phrases in the
    # actual task. A VLM label cannot manufacture a Chinese-to-English mapping.
    vocabulary.update({s.query: canonical(s.query) for s in semantics})
    occupied, found = set(), []
    for token, query in sorted(vocabulary.items(), key=lambda item: (-len(item[0]), item[0])):
        pattern = (r"(?<![a-z])" + re.escape(token) + r"(?![a-z])"
                   if token.isascii() else re.escape(token))
        for match in re.finditer(pattern, task.lower()):
            positions = set(range(match.start(), match.end()))
            if occupied & positions:
                continue
            occupied.update(positions)
            found.append({"query": query, "token": match.group(), "offset": match.start(),
                          "end_offset": match.end()})
    return sorted(found, key=lambda mention: mention["offset"])


def _minimum_count(task, mention):
    prefix = task[:mention["offset"]].lower()
    count = r"(" + "|".join(sorted(COUNT_WORDS, key=len, reverse=True)) + r"|\d+)\s*"
    match = re.search(count + r"(?:个|只|位|枚|根|件|支)?\s*$", prefix)
    if match:
        value = match.group(1)
        return COUNT_WORDS[value] if value in COUNT_WORDS else int(value)
    # A plural names more than one target; exact cardinality remains uncertain.
    return 2 if mention["token"] == "people" or (
        mention["token"] in ALIASES and mention["token"].endswith("s")) else 1


def compose_photography_queries(task, semantics):
    from_task = list(dict.fromkeys(m["query"] for m in _mentions(task, semantics)))
    from_vlm = english_queries([s.query for s in semantics])
    return {"dictionary_version": "production-photography-english-v1", "from_task": from_task,
            "from_vlm": from_vlm, "manual": [],
            "merged": list(dict.fromkeys(from_task + from_vlm)),
            "fallback": from_task if not semantics else [], "task_text": task,
            "source_policy": "actual_task_vocabulary+validated_semantic_queries"}


def resolve_photography_scope(task, semantics, main_ids):
    mentions = _mentions(task, semantics)
    required_mentions, auxiliary_mentions, unknown, protection, requested_texts = [], [], [], [], []
    output_instructions = []
    units = []
    for clause in re.finditer(r"[^，,。;；\n]+", task):
        text = clause.group()
        present = [m for m in mentions if clause.start() <= m["offset"] < clause.end()]
        if re.fullmatch(_OUTPUT_INSTRUCTION, text.strip()):
            output_instructions.append(text)
            continue
        action = re.search(_ACTION, text, re.IGNORECASE)
        auxiliary = re.search(_AUXILIARY, text, re.IGNORECASE)
        # A leading request remains required even if its tail discusses
        # background. Clauses that begin with retention are protection advice.
        if auxiliary and (not action or auxiliary.start() < action.start()):
            auxiliary_mentions.extend(present)
            protection.append(text)
            continue
        if not action:
            auxiliary_mentions.extend(present)
            continue
        end = clause.end()
        if auxiliary:
            end = clause.start() + auxiliary.start()
            protection.append(task[end:clause.end()])
        requested = [m for m in present if m["offset"] < end]
        requested_texts.append(task[clause.start():end])
        auxiliary_mentions.extend(m for m in present if m["offset"] >= end)
        required_mentions.extend(requested)
        residual = list(task[clause.start():end])
        for mention in requested:
            start, finish = mention["offset"] - clause.start(), mention["end_offset"] - clause.start()
            residual[start:finish] = " " * (finish - start)
        value = "".join(residual)
        # In photography, an owner's eyes/ears/whiskers are framing instructions;
        # an explicit localization verb instead requests independent geometry.
        if not re.search(_GEOMETRY_ACTION, text, re.IGNORECASE):
            value = re.sub(_DETAIL, "", value)
        value = re.sub(_NOISE, "", value, flags=re.IGNORECASE).strip()
        if value:
            unknown.append(value)
    for query in dict.fromkeys(m["query"] for m in required_mentions):
        matches = [m for m in required_mentions if m["query"] == query]
        units.append({"unit_id": "task:" + query, "query": query, "target_level": "category",
                      "minimum_count": max(_minimum_count(task, m) for m in matches),
                      "evidence": [task[m["offset"]:m["end_offset"]] for m in matches]})
    for value in dict.fromkeys(unknown):
        units.append({"unit_id": "task:unparsed:" + value, "query": value,
                      "target_level": "unknown", "minimum_count": 1,
                      "evidence": [task], "unresolved": True, "support_status": "unknown"})
    roles, unresolved = [], []
    required_queries = {m["query"] for m in required_mentions}
    auxiliary_queries = {m["query"] for m in auxiliary_mentions}
    for sem in semantics:
        query = canonical(sem.query)
        required = query in required_queries
        role = ("main_target" if sem.object_id in main_ids else "required") if required else (
            "auxiliary" if query in auxiliary_queries else "background")
        if not required and sem.object_id in main_ids:
            role = "unknown"
            unresolved.append("VLM主目标缺少用户任务的明确类别证据：" + sem.object_id)
        roles.append({"object_id": sem.object_id, "query_original": sem.query,
                      "query_normalized": query, "task_family": query, "role": role,
                      "required": required, "evidence": ["task:" + query] if required else []})
    missing = [u["unit_id"] for u in units if u.get("unresolved") or len(
        [s for s in semantics if canonical(s.query) == u["query"]]) < u["minimum_count"]]
    if not required_queries:
        unresolved.append("任务缺少明确的摄影主体类别")
    if unknown:
        unresolved.append("任务包含未解析的必需目标/部件")
    if re.search(r"所有|全部|\b(?:all|both)\b", task, re.IGNORECASE):
        unresolved.append("完整可见实例数量未经证实")
        missing.extend(u["unit_id"] for u in units if u["unit_id"] not in missing)
    identity_markers = any(re.search(_ENTITY, text, re.IGNORECASE) for text in requested_texts)
    return {"rule_version": SCOPE_RULE_VERSION,
            "evidence_source": "actual_user_task+saved_semantics", "required_units": units,
            "object_roles": roles, "missing_semantic_units": missing,
            "unresolved": unresolved, "status": "unknown" if unresolved else "known",
            "protection_instructions": protection, "entity_identity_requested": identity_markers,
            "output_instructions": output_instructions,
            "denominator_policy": "preserve all explicit required targets/counts"}
