"""Conservative task units from the actual common task, without any GT channel."""
from __future__ import annotations

import re

from vision_lab_tool.detector_queries import ALIASES, COCO_CLASSES, TASK_DICTIONARY, canonical

SCOPE_RULE_VERSION = "explicit-task-units-v3"
COUNT_WORDS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
               "七": 7, "八": 8, "九": 9, "十": 10, "one": 1, "two": 2, "three": 3,
               "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
SUBTARGET_MARKERS = {
    "part": r"把手|杯柄|杯沿|杯底|徽标|头部|脚部|\b(?:handle|rim|logo|head|foot)\b",
    "region": r"杯口|\b(?:interior|inside region)\b",
}
# These families determine only task membership. They are NOT detector aliases:
# e.g. cartoon woman can be a requested person while never becoming a live person.
TASK_FAMILIES = {
    "cartoon woman": "person", "cartoon man": "person", "depicted person": "person",
    "woman": "person", "man": "person", "boy": "person", "girl": "person",
    "metal tool": "instrument", "metal instrument": "instrument",
}
LEVEL_MARKERS = {
    "part": ("handle", "opening", "rim", "rod", "tube", "hand", "component", "part"),
    "region": ("region", "inside", "interior", "surface", "area"),
    "combination": ("arrangement", "group", "combination"),
}


def task_family(query):
    value = canonical(query)
    return TASK_FAMILIES.get(value, value)


def level_compatible(obj, sem, detector, components):
    """A broad instance box cannot serve as an arbitrary part/region."""
    if obj.target_level == sem.target_level:
        return True
    if obj.target_level not in {"instance", "unknown"}:
        return False
    if sem.target_level in {"whole", "instance"}:
        return True
    if detector == "yolo26" or sem.target_level == "unknown":
        return False
    markers = LEVEL_MARKERS.get(sem.target_level, ())
    query = canonical(sem.query)
    return query in components and any(word in query.split() for word in markers)


def _clause(task, position):
    start = max(task.rfind(mark, 0, position) for mark in "，,。;；\n") + 1
    end = min([p for mark in "，,。;；\n" if (p := task.find(mark, position)) >= 0]
              or [len(task)])
    return task[start:end]


def _nonrequired_clause(clause):
    return bool(re.search(r"不定位|无需定位|忽略|仅作背景|do not locate|ignore|"
                          r"尺度关系|上下文|context|scale relation", clause, re.IGNORECASE))


def _task_mentions(task):
    mentions = []
    occupied = set()
    vocabulary = dict(TASK_DICTIONARY)
    vocabulary.update({q: canonical(q) for q in set(COCO_CLASSES) | set(ALIASES)
                       | set(TASK_DICTIONARY.values()) | set(TASK_FAMILIES)})
    for token, query in sorted(vocabulary.items(), key=lambda item: (-len(item[0]), item[0])):
        pattern = (r"(?<![a-z])" + re.escape(token) + r"(?![a-z])"
                   if token.isascii() else re.escape(token))
        for match in re.finditer(pattern, task.lower()):
            span = set(range(match.start(), match.end()))
            if span & occupied:
                continue
            occupied.update(span)
            start = max(task.rfind(mark, 0, match.start()) for mark in "，,。;；\n") + 1
            end = min([p for mark in "，,。;；\n"
                       if (p := task.find(mark, match.end())) >= 0] or [len(task)])
            clause = task[start:end]
            role = "required"
            if re.search(r"(?:不定位|无需定位|忽略|仅作背景|do not locate|ignore)", clause):
                role = "background"
            elif re.search(r"(?:尺度关系|上下文|context|scale relation)", clause):
                role = "auxiliary"
            mentions.append({"query": task_family(query), "token": match.group(),
                             "role": role, "evidence": clause, "offset": match.start(),
                             "end_offset": match.end()})
    return sorted(mentions, key=lambda item: item["offset"])


def _unparsed_conjuncts(task, mentions):
    """Unknown named targets after a conjunction remain in the task inventory."""
    unresolved = []
    joins = list(re.finditer(r"以及|和|与|、|\band\b|\bplus\b", task, re.IGNORECASE))
    for index, join in enumerate(joins):
        if _nonrequired_clause(_clause(task, join.start())):
            continue
        ends = [p for mark in "，,。;；\n" if (p := task.find(mark, join.end())) >= 0]
        if index + 1 < len(joins):
            ends.append(joins[index + 1].start())
        end = min(ends or [len(task)])
        fragment = task[join.end():end].strip()
        if not fragment or any(join.end() <= m["offset"] < end for m in mentions):
            continue
        if re.search(r"杯中|杯内|部件|parts|components|整体|whole|边界|边缘|实体|归属", fragment):
            continue
        if re.match(r"保留|区分|说明|避免|不要|不用|keep|preserve|distinguish", fragment,
                    re.IGNORECASE):
            continue
        unresolved.append(fragment)
    return unresolved


def _unknown_target_prefix(task, mentions):
    """Do not mistake a known context object for an unknown requested head noun."""
    first = min((m["offset"] for m in mentions if m["role"] == "required"), default=len(task))
    prefix = task[:first].strip()
    if not re.search(r"定位|找出|框出|识别|\b(?:locate|identify|detect|find)\b", prefix,
                     re.IGNORECASE):
        return ""
    # Only lexical scaffolding is discarded. Unrecognized nouns, relations and
    # conjunctions remain evidence that the scope cannot yet be resolved.
    noise = (r"请|分别|定位|找出|框出|识别|照片中|画面中|图中|可见|的|所有|全部|金属|"
             r"一对|(?:[一二两三四五六七八九十]|\d+)(?:个|只|位|枚|根|件|支)?|"
             r"\b(?:please|locate|identify|detect|find|the|a|an|visible|whole|all|"
             r"one|two|three|four|five|six|seven|eight|nine|ten)\b")
    return re.sub(noise, "", prefix, flags=re.IGNORECASE).strip()


def _minimum_count(task, mention):
    prefix = task[:mention["offset"]].lower()
    pattern = r"(" + "|".join(sorted(COUNT_WORDS, key=len, reverse=True)) + r"|\d+)\s*"
    match = re.search(pattern + r"(?:个|只|位|枚|根|件|支)?\s*$", prefix)
    if match:
        value = match.group(1)
        return COUNT_WORDS[value] if value in COUNT_WORDS else int(value)
    return 1


def _target_residuals(task, mentions):
    """Unknown modifiers before or after a known noun prevent a complete claim.

    This is a bounded grammar, not a general natural-language parser. Only
    recognized category spans and explicit task scaffolding are consumed.
    """
    residuals = []
    for match in re.finditer(r"[^，,。;；\n]+", task):
        clause = match.group()
        if _nonrequired_clause(clause):
            continue
        if match.start() and not re.search(
                r"定位|找出|框出|识别|\b(?:locate|identify|detect|find)\b", clause,
                re.IGNORECASE):
            continue
        words = list(clause)
        for mention in mentions:
            if match.start() <= mention["offset"] < match.end():
                start = mention["offset"] - match.start()
                end = mention["end_offset"] - match.start()
                words[start:end] = " " * (end - start)
        value = "".join(words)
        noise = (r"请|分别|定位|找出|框出|识别|照片中|画面中|图中|可见|的|所有|全部|金属|"
                 r"整体|主体|实例|候选|目标|以及|和|与|、|部件|杯中|杯内|"
                 r"(?:[一二两三四五六七八九十]|\d+)(?:个|只|位|枚|根|件|支)?|"
                 r"\b(?:please|locate|identify|detect|find|the|a|an|visible|whole|all|"
                 r"one|two|three|four|five|six|seven|eight|nine|ten|and|plus|parts|components)\b")
        if re.search(r"杯中|杯内|陶轮|轮面|pottery wheel", clause, re.IGNORECASE):
            noise += r"|区域|\binside region\b"
        residual = re.sub(noise, "", value, flags=re.IGNORECASE).strip()
        if residual:
            residuals.append(residual)
    return residuals


def resolve_task_scope(task, semantics=(), main_ids=()):
    """Return required units and object roles; main IDs cannot create requirements.

    Class mentions are a lower bound. Explicit regions, unresolved visible
    components and counts remain independent units even when VLM omitted them.
    """
    task = task or ""
    mentions = _task_mentions(task)
    requested = list(dict.fromkeys(m["query"] for m in mentions if m["role"] == "required"))
    units = [{"unit_id": "task:" + q, "query": q, "target_level": "category",
              "minimum_count": max([_minimum_count(task, m) for m in mentions
                                    if m["query"] == q and m["role"] == "required"] or [1]),
              "evidence": [m["evidence"] for m in mentions
                                               if m["query"] == q and m["role"] == "required"]}
             for q in requested]
    unresolved = []
    if not requested:
        unresolved.append("共同任务缺少可识别的必需目标证据")
    if re.search(r"(?:另一|其他|未知|未指定).{0,8}(?:物件|对象|目标)|unknown object", task):
        unresolved.append("任务包含未解析的必需目标")
    unknown_prefix = _unknown_target_prefix(task, mentions)
    for fragment in list(dict.fromkeys(_unparsed_conjuncts(task, mentions)
                                     + ([unknown_prefix] if unknown_prefix else [])
                                     + _target_residuals(task, mentions))):
        units.append({"unit_id": "task:unparsed:" + fragment, "query": fragment,
                      "target_level": "unknown", "minimum_count": 1, "evidence": [task],
                      "unresolved": True, "support_status": "unknown"})
        unresolved.append("未解析的并列必需目标：" + fragment)
    for level, pattern in SUBTARGET_MARKERS.items():
        for match in re.finditer(pattern, task, re.IGNORECASE):
            if _nonrequired_clause(_clause(task, match.start())):
                continue
            units.append({"unit_id": "task:subtarget:" + match.group(), "query": match.group(),
                          "target_level": level, "minimum_count": 1, "evidence": [task],
                          "support_status": "unknown", "unresolved": True})
            unresolved.append("明确部件/区域需独立证据：" + match.group())
    if re.search(r"(?:部件|parts|components)", task):
        units.append({"unit_id": "task:visible_parts", "query": "visible parts",
                      "target_level": "part", "minimum_count": 1,
                      "evidence": [task], "unresolved": True})
        unresolved.append("可见部件完整清单未知；整体不能替代部件")
    if re.search(r"杯中|杯内|cup inside|cup interior", task):
        units.append({"unit_id": "task:cup_inside_region", "query": "cup inside region",
                      "target_level": "region", "minimum_count": 1, "evidence": [task]})
    for unit in units:
        if unit["query"] == "hand" and re.search(r"两只手|双手|two hands|both hands", task):
            unit["minimum_count"] = 2
        if unit["query"] == "pottery wheel" and re.search(r"可见区域|轮面|surface", task):
            unit["target_level"] = "region"
    roles = []
    for sem in semantics:
        family = task_family(sem.query)
        explicit_unit = next((u for u in units if canonical(sem.query) == u["query"]), None)
        required = family in requested or explicit_unit is not None
        # A parent's presence alone is not evidence that its children are required.
        if not required and sem.target_level == "part" and any(
                u["unit_id"] == "task:visible_parts" for u in units):
            required = True
        if required:
            role = "main_target" if sem.object_id in main_ids else "required"
            evidence = [u["unit_id"] for u in units if u["query"] in {family, canonical(sem.query)}
                        or (u["target_level"] == "part" and sem.target_level == "part")]
        else:
            role = "unknown" if not requested else "background"
            evidence = []
            if any(m["query"] == family and m["role"] == "auxiliary" for m in mentions):
                role = "auxiliary"
            if sem.object_id in main_ids and role == "background":
                role = "unknown"
                unresolved.append("VLM主目标无共同任务范围证据：" + sem.object_id)
        roles.append({"object_id": sem.object_id, "query_original": sem.query,
                      "query_normalized": canonical(sem.query), "task_family": family,
                      "role": role, "required": required, "evidence": evidence})
    missing = []
    for unit in units:
        matching = [s for s in semantics if task_family(s.query) == unit["query"]
                    or canonical(s.query) == unit["query"]]
        if unit["target_level"] not in {"category", "whole", "instance"}:
            matching = [s for s in matching if s.target_level == unit["target_level"]]
        if unit.get("unresolved") or len(matching) < unit["minimum_count"]:
            missing.append(unit["unit_id"])
    if re.search(r"所有|全部|人物实例|人物候选|all people|all instances", task):
        unresolved.append("可见实例完整数量未经独立范围证据确定")
    return {"rule_version": SCOPE_RULE_VERSION, "evidence_source": "actual_common_task+saved_semantics",
            "required_units": units, "object_roles": roles,
            "missing_semantic_units": missing, "unresolved": list(dict.fromkeys(unresolved)),
            "status": "unknown" if unresolved else "known",
            "denominator_policy": "preserve requested units, including missing and unsupported"}
