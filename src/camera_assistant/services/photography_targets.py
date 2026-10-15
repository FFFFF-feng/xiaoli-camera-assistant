"""Evidence-preserving photography grammar, separate from frozen lab rules.

Known photographic operations get explicit roles. Unparsed fragments retain
their original clause: a request or imaging goal is not automatically an object.
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

SCOPE_RULE_VERSION = "production-photography-scope-v4"
PRODUCTION_DICTIONARY = {
    **TASK_DICTIONARY,
    "瀑布": "waterfall", "树林": "forest", "森林": "forest", "岩石": "rock",
    "瓶子": "bottle", "花朵": "flower", "骑车人": "person", "骑手": "person",
    "骑自行车的人": "person", "骑行人物": "person", "单车": "bicycle",
    "飞鸟": "bird", "鸟儿": "bird",
    "窗框": "window frame", "窗外景色": "landscape", "窗外风景": "landscape",
    "街景": "street", "山景": "mountain",
}
_ACTION = (r"定位|找出|框出|识别|突出|重拍|重新拍摄|拍摄|强调|聚焦|表现|体现|捕捉|"
           r"只保留|作为主体|利用|凝固|定格|冻结|拍|"
           r"\b(?:locate|identify|detect|find|photograph|highlight|capture|focus|freeze)\b")
_GEOMETRY_ACTION = r"定位|找出|框出|识别|\b(?:locate|identify|detect|find)\b"
_PRESERVE = (r"完整保留|(?<!只)保留|保护|不裁掉|不要裁掉|别裁掉|避免裁掉|保持完整|别截断|不截断|"
             r"\b(?:preserve|retain|keep)\b")
_CONTEXT = r"简化|忽略|无需定位|不定位|仅作背景|背景|上下文|\b(?:ignore|background|context)\b"
_DETAIL = (r"完整身体|完整骑行主体|全身|身体完整|身体|轮廓|双眼|眼睛|耳朵|胡须|"
           r"视线|头部|脚部|把手|杯柄|杯沿|杯底|徽标|杯口")
_ENTITY = (r"倒影|反射|镜子|镜中|镜里|玻璃中|画中|画里的|海报|卡通|模型|雕像|模特假人|"
           r"\b(?:reflection|reflected|depiction|depicted|mannequin|cartoon|poster|painting|scale model)\b")
_OUTPUT = (r"给出|提供|说明|解释|怎样|如何|怎么|建议|取景|构图|设置参数|参数设置|曝光取舍|"
           r"曝光调整|曝光建议|曝光|\b(?:how|advice|suggest|composition|framing|settings|exposure)\b")
_GOALS = {
    "freeze_motion": r"凝固|定格|冻结|\bfreeze\b",
    "background_separation": r"背景(?:分离|虚化)|(?:分离|虚化)背景|"
                             r"(?:与|和)(?:(?!以及|和|与|、).){0,30}背景分离|"
                             r"从(?:(?!以及|和|与|、).){0,30}背景中(?:分离|突出)|"
                             r"\b(?:background separation|blur the background)\b",
    "subject_outline": r"主体轮廓|轮廓(?:更)?清楚|剪影|\bsilhouette\b",
    "scene_layers": r"(?:画面)?层次(?:更)?清楚|层次感|尺度关系|环境关系",
    "highlight_retention": r"减少高光溢出|避免高光溢出|保护高光|保留高光",
    "water_motion": r"水流拉丝|水流柔滑|拉丝水流",
}
# No wildcard here consumes an arbitrary object of an output request.
_OPERATIONS = (r"可以执行的|可执行的|构图调整|构图建议|重拍建议|拍摄建议|"
               r"用三脚架|没有ND减光镜|没有ND滤镜|目前|希望|时|对|"
               r"\b(?:reshoot|reshooting)\b")
_CONTEXT_DESCRIPTORS = (r"完整|轮廓|动作|运动|骑行|窗框形成的自然取景框|自然取景框|窗框|"
               r"窗外景色|窗外风景|周围环境|"
               r"环境|天空颜色|夜街灯光|水面|街景|市场整体热闹氛围|近处|人物关系|反射关系|倒影关系|"
               r"树林层次|层次|落叶|视线空间|留出|形成|清楚|让|减少|高光溢出|"
               r"\b(?:motion|action|whole body|full body|blur|the background)\b")
_CONNECTORS = (r"请|分别|照片中|画面中|图中|可见|的|主体|整体|突出|重拍|重新拍摄|拍摄|拍|"
               r"强调|聚焦|表现|体现|捕捉|定位|找出|框出|识别|利用|只保留|也作为主体|作为主体|"
               r"完整保留|保留|保护|保持完整|不裁掉|不要裁掉|别裁掉|避免裁掉|别截断|不截断|"
               r"以及|和|与|、|并|用|所有|全部|(?:[一二两三四五六七八九十]|\d+)(?:个|只|位|枚|根|件|支)?|"
               r"\b(?:please|locate|identify|detect|find|photograph|highlight|capture|focus|freeze|"
               r"preserve|retain|keep|the|a|an|of|on|visible|whole|and|plus|one|two|three|four|five|six|"
               r"seven|eight|nine|ten|all|both)\b")


def _mentions(task, semantics):
    vocabulary = dict(PRODUCTION_DICTIONARY)
    vocabulary.update({q: canonical(q) for q in set(COCO_CLASSES) | set(ALIASES)
                       | set(PRODUCTION_DICTIONARY.values())})
    # An English open-vocabulary label must occur literally in the user text.
    # VLM labels cannot manufacture Chinese-to-English mappings.
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
    if not match:
        # Some frozen dictionary entries contain their own count (两只手).
        match = re.match(count + r"(?:个|只|位|枚|根|件|支)", mention["token"])
    if match:
        value = match.group(1)
        return COUNT_WORDS[value] if value in COUNT_WORDS else int(value)
    return 2 if mention["token"] in {"people", "人群"} or (
        mention["token"] in ALIASES and mention["token"].endswith("s")) else 1


def _evidence(text, start, end, **fields):
    return {"text": text[start:end], "start": start, "end": end, **fields}


def _mask(pattern, text, consumed):
    for match in re.finditer(pattern, text, re.IGNORECASE):
        consumed.update(range(match.start(), match.end()))


def compose_photography_queries(task, semantics):
    from_task = list(dict.fromkeys(m["query"] for m in _mentions(task, semantics)))
    from_vlm = english_queries([s.query for s in semantics])
    return {"dictionary_version": "production-photography-english-v2", "from_task": from_task,
            "from_vlm": from_vlm, "manual": [],
            "merged": list(dict.fromkeys(from_task + from_vlm)),
            "fallback": from_task if not semantics else [], "task_text": task,
            "source_policy": "actual_task_vocabulary+validated_semantic_queries"}


def resolve_photography_scope(task, semantics, main_ids):
    mentions = _mentions(task, semantics)
    required_mentions, auxiliary_mentions, protected_mentions = [], [], []
    protection, outputs, goals = [], [], []
    uncertainties, unknown_targets, identities, clauses, locations = [], [], [], [], []
    # A joined retention instruction stays protection, rather than introducing
    # another main subject (e.g. waterfall followed by surrounding trees).
    for clause in re.finditer(r"[^，,。;；\n！？?!]+", task):
        for segment in re.finditer(r".+?(?=并(?:保留|保护|保持完整)|$)", clause.group()):
            start, end = clause.start() + segment.start(), clause.start() + segment.end()
            text = task[start:end]
            present = [m for m in mentions if start <= m["offset"] < end]
            action = re.search(_ACTION, text, re.IGNORECASE)
            preserve = re.search(_PRESERVE, text, re.IGNORECASE)
            context = re.search(_CONTEXT, text, re.IGNORECASE)
            output = re.search(_OUTPUT, text, re.IGNORECASE)
            role = "subject" if action else "unparsed"
            if preserve and (not action or preserve.start() < action.start()):
                role = "protection"
            elif context and (not action or context.start() < action.start()):
                role = "context"
            elif output and not present:
                role = "output"
            elif output and not action:
                role = "subject"  # named entities in questions remain requested
            clauses.append(_evidence(task, start, end, role=role))
            if preserve:
                protection.append(_evidence(task, start, end, kind="preservation"))
            if output:
                outputs.append(_evidence(task, start, end, kind="output_request"))
            consumed = set()
            for goal, expression in _GOALS.items():
                for match in re.finditer(expression, text, re.IGNORECASE):
                    goals.append(_evidence(task, start + match.start(), start + match.end(),
                                           goal=goal))
                    consumed.update(range(match.start(), match.end()))
            for mention in present:
                prefix = task[start:mention["offset"]]
                # Only a prefix directly qualifying a named entity can be a
                # location. A conjunction or an earlier named entity preserves
                # separate-subject and explicit part requirements.
                if re.search(r"和|与|、|以及", prefix) or any(
                    other["offset"] < mention["offset"] for other in present
                ):
                    continue
                lead = re.match(r"^(?:(?:" + _ACTION + "|" + _PRESERVE + r")|请|所有|全部|"
                                r"(?:[一二两三四五六七八九十]|\d+)(?:个|只|位)?)*", prefix)
                offset = lead.end() if lead else 0
                location = prefix[offset:]
                if not location or not (re.fullmatch(r"[^，。;；]+(?:上|旁|边|中|里面|前|后)的?", location)
                    or location in {"海岸", "岸边", "山顶", "窗边", "水边", "室内", "室外"}):
                    continue
                loc_start = start + offset
                locations.append(_evidence(task, loc_start, mention["offset"],
                    subject_query=mention["query"], anchor_text=location.rstrip("的"),
                    verification="unverified", missing_evidence="位置或环境归属未获独立核验"))
                consumed.update(range(offset, len(prefix)))
                # Keep a quantity separated from its noun by the location phrase.
                mention["minimum_count_hint"] = _minimum_count(task, {**mention, "offset": loc_start})
            for mention in present:
                if role == "subject":
                    required_mentions.append({**mention, "clause_start": start, "clause_end": end})
                else:
                    auxiliary_mentions.append(mention)
                    if role == "protection":
                        protected_mentions.append({**mention, "clause_start": start,
                                                   "clause_end": end})
                consumed.update(range(mention["offset"] - start, mention["end_offset"] - start))
            if role in {"subject", "protection"}:
                for match in re.finditer(_ENTITY, text, re.IGNORECASE):
                    identities.append(_evidence(task, start + match.start(), start + match.end(),
                                                verification="not_proven_by_category_box"))
                    consumed.update(range(match.start(), match.end()))
            # Owner details are framing requirements. An explicit localization
            # verb instead requests independent part geometry, so keep it unknown.
            if not re.search(_GEOMETRY_ACTION, text, re.IGNORECASE):
                for match in re.finditer(_DETAIL, text, re.IGNORECASE):
                    preceding = [m for m in present if m["end_offset"] <= start + match.start()]
                    owner = preceding[-1] if preceding else None
                    owner_tail = text[owner["end_offset"] - start:match.start()] if owner else ""
                    owned_detail = bool(owner and re.fullmatch(
                        r"的(?:主体)?(?:(?:" + _DETAIL + r")|以及|和|与|、)*", owner_tail))
                    if role == "subject" and not owned_detail:
                        continue
                    protection.append(_evidence(task, start + match.start(), start + match.end(),
                                                kind="subject_detail"))
                    consumed.update(range(match.start(), match.end()))
            for expression in (_OUTPUT, _OPERATIONS, _CONNECTORS):
                _mask(expression, text, consumed)
            if role != "subject":
                _mask(_CONTEXT_DESCRIPTORS, text, consumed)
            if any(goal["goal"] == "freeze_motion" and start <= goal["start"] < end for goal in goals):
                _mask(r"动作|运动|骑行|\b(?:motion|action)\b", text, consumed)
            # Labelled context retains its original text. It is never promoted
            # into a requested subject, including unknown background descriptors.
            if role == "context":
                continue
            residue = "".join(" " if i in consumed else ch for i, ch in enumerate(text))
            fragments = [value.strip() for value in re.split(r"\s+", residue) if value.strip()]
            for value in fragments:
                detail = {"fragment": value, "evidence": text, "start": start, "end": end,
                          "kind": "unparsed_target" if role == "subject" else "unparsed_intent"}
                uncertainties.append(detail)
                if role == "subject":
                    unknown_targets.append(detail)

    # Retention-only requests still name entities. They constrain the subject
    # set, rather than becoming a parsing failure or an arbitrary single pick.
    protection_anchor = not required_mentions and bool(protected_mentions)
    if protection_anchor:
        required_mentions = list(protected_mentions)
    protected_units = []
    for mention in protected_mentions:
        clause = task[mention["clause_start"]:mention["clause_end"]]
        protected_units.append({
            "query": mention["query"], "minimum_count": _minimum_count(task, mention),
            "user_evidence": [clause],
            "geometry_requirement": "complete_visible_extent" if re.search(
                r"完整|全身|别裁掉|不裁掉|不要裁掉|别截断|不截断|保持完整|\bwhole|\bfull", clause,
                re.IGNORECASE,
            ) else "relationship_unverified",
        })
    units = []
    for query in dict.fromkeys(m["query"] for m in required_mentions):
        matches = [m for m in required_mentions if m["query"] == query]
        constraints = matches + [m for m in protected_mentions if m["query"] == query
                                 and m not in matches]
        per_clause = {}
        for mention in constraints:
            per_clause.setdefault(mention["clause_start"], []).append(mention)
        minimum = max(sum(max(_minimum_count(task, m), m.get("minimum_count_hint", 1)) for m in group)
                      for group in per_clause.values())
        units.append({"unit_id": "task:" + query, "query": query, "target_level": "category",
                      "minimum_count": minimum,
                      "source_role": "protection_anchor" if protection_anchor else "subject",
                      "evidence": [task[m["offset"]:m["end_offset"]] for m in matches],
                      "user_evidence": list(dict.fromkeys(
                          task[m["clause_start"]:m["clause_end"]] for m in matches)),
                      "identity_requirements": [item for item in identities if any(
                          m["clause_start"] <= item["start"] < m["clause_end"] for m in matches)]})
    for item in unknown_targets:
        value = item["fragment"]
        if any(unit["unit_id"] == "task:unparsed:" + value for unit in units):
            continue
        units.append({"unit_id": "task:unparsed:" + value, "query": value,
                      "target_level": "unknown", "minimum_count": 1,
                      "evidence": [item["evidence"]], "unresolved": True, "support_status": "unknown"})
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
    if uncertainties:
        unresolved.append("拍摄意图存在未解析片段；保留原文，不能作为已验证主体要求")
    if locations:
        unresolved.append("用户位置或环境约束已解析，但归属尚未独立核验")
    all_instances = bool(re.search(r"所有|全部|\b(?:all|both)\b", task, re.IGNORECASE))
    if all_instances:
        unresolved.append("完整可见实例数量未经证实")
        missing.extend(u["unit_id"] for u in units if u["unit_id"] not in missing)
    return {"rule_version": SCOPE_RULE_VERSION,
            "evidence_source": "actual_user_task+saved_semantics", "required_units": units,
            "object_roles": roles, "missing_semantic_units": missing,
            "unresolved": unresolved, "status": "unknown" if unresolved else "known",
            "protection_instructions": list(dict.fromkeys(item["text"] for item in protection)),
            "preservation_requirements": protection, "imaging_goals": goals,
            "protected_units": protected_units,
            "location_constraints": locations,
            "intent_parse_uncertainties": uncertainties, "clauses": clauses,
            "entity_identity_requested": bool(identities), "identity_requirements": identities,
            "all_instances_requested": all_instances,
            "output_instructions": list(dict.fromkeys(item["text"] for item in outputs)),
            "output_requests": outputs,
            "denominator_policy": "preserve all explicit required targets/counts"}
