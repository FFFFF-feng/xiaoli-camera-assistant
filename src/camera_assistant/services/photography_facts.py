"""Shared, locally controlled photographic constraints for both advice branches.

The checks cover specific causal relationships, not arbitrary natural-language
truth. No unflagged sentence is certified correct and no extra model is called.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Literal

from camera_assistant.composition_models import CompositionAdvice, CompositionProposal
from camera_assistant.models import CameraProfile, CameraRecommendation, PhoneProfile, SceneAnalysis, UserRequest


@dataclass(frozen=True)
class PhotographyFacts:
    device_type: str
    ibis: Literal["present", "absent", "unknown"]
    motion: str
    support: Literal["tripod", "handheld", "unspecified"]
    white_balance_goal: Literal["preserve_warmth", "neutralize", "unspecified"]
    declared_light: str | None
    compare_center_thirds: bool
    preserve_reflection: bool

    @property
    def white_balance_instruction(self) -> str:
        if self.white_balance_goal == "preserve_warmth":
            return "自动白平衡试拍后锁定，按预览向暖微调以保留暖色氛围"
        return "自动白平衡试拍，有中性参照时用自定义白平衡中和偏色"

    def prompt(self) -> str:
        return (json.dumps(asdict(self), ensure_ascii=False) + "\n"
            "以下为本地受控事实，两分支都必须遵守：高速快门有助于减轻相机抖动和凝固主体运动，"
            "不能声称高速快门使取景不稳定；机身防抖不能代替凝固主体运动的快门。"
            "ibis=absent不得指导开启或依赖机身防抖，ibis=unknown不得猜测具备或缺少防抖；"
            "镜头防抖未确认，只能以支持时为条件。support=tripod时按三脚架处理。"
            "照片暖色只说明成像色调，不能确认钨丝灯等光源。"
            + (f"白平衡统一采用：{self.white_balance_instruction}。钨丝灯预设通常中和暖光，不能保证保暖。"
               if self.white_balance_goal != "unspecified" else "光源不明时白平衡按预览试拍调整，不承诺固定预设效果。")
            + "compare_center_thirds=true时比较原有居中/中轴取景与偏置三分的利弊；"
            "推荐偏置时说明会牺牲严格中轴对称，不能同时强制左右对称与右侧三分。"
            "保留原构图也是有效推荐。二维示意图只支持统一取景变换，真实侧移/蹲下后的透视与遮挡"
            "须现场观察试拍，不得声称推荐图已实现视差改善。")


_facts: ContextVar[PhotographyFacts | None] = ContextVar("photography_facts", default=None)


def build_photography_facts(request: UserRequest, scene: SceneAnalysis | None,
                            camera: CameraProfile | PhoneProfile | None) -> PhotographyFacts:
    intent = request.intent
    neutralize = bool(re.search(r"(?:中和|消除|校正|去除|纠正).{0,10}(?:偏色|偏黄|暖色)|(?:还原|恢复).{0,8}(?:中性|真实颜色)", intent))
    preserve = bool(re.search(r"(?:保留|保持|营造|呈现|想要).{0,16}(?:暖色|暖调|温暖)", intent))
    if re.search(r"(?:不想|不要|无需|不必).{0,4}(?:保留|保持).{0,8}(?:暖色|暖调)", intent):
        preserve = False
    # Generic demonstration profiles can contain conservative exposure defaults;
    # these never establish the unknown user's actual stabilization hardware.
    ibis = None if getattr(camera, "profile_id", "generic_unknown").startswith("generic_") else getattr(camera, "ibis_stops", None)
    return PhotographyFacts(
        device_type=request.device_type,
        ibis="unknown" if ibis is None else "present" if ibis > 0 else "absent",
        motion={"快速": "fast", "缓慢": "slow", "静止": "static"}.get(request.subject_motion, scene.subject_motion if scene else "unknown"),
        support="tripod" if request.tripod else "handheld" if request.handheld else "unspecified",
        white_balance_goal="neutralize" if neutralize else "preserve_warmth" if preserve else "unspecified",
        declared_light=request.lighting_type,
        compare_center_thirds=bool(re.search(r"比较|对比|取舍", intent) and "居中" in intent and "三分" in intent),
        preserve_reflection=bool(re.search(r"倒影|镜像", intent)),
    )


def photography_facts(request: UserRequest, scene: SceneAnalysis,
                      camera: CameraProfile | PhoneProfile | None = None) -> PhotographyFacts:
    return _facts.get() or build_photography_facts(request, scene, camera)


@contextmanager
def use_photography_facts(facts: PhotographyFacts):
    token = _facts.set(facts)
    try:
        yield
    finally:
        _facts.reset(token)


def _clauses(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[，,。；;！!？?\n]", text) if part.strip()]


def _negated(text: str, target: str) -> bool:
    # Scope negation to the predicate near the relevant target, not a whole
    # sentence: "不能降低ISO，但可以开启IBIS" still contains a positive claim.
    return bool(re.search(r"(?:不能|不会|不应|不得|不要|不具备|没有|未确认|尚未确认|不依赖|不可|无需|无)"
                          r"[^，。；;]{0,12}" + target, text, re.IGNORECASE)
                or re.search(target + r"[^，。；;]{0,8}(?:不能|不会|未确认|未知|并非|不支持|不具备)", text, re.IGNORECASE))


def semantic_issues(text: str, facts: PhotographyFacts) -> set[str]:
    """Detect affirmative relationships; valid negatives/conditions remain valid."""
    issues: set[str] = set()
    for clause in _clauses(text):
        fast = r"(?:高速快门|快门(?:速度)?(?:过高|过快)|提高快门速度)"
        # Direction belongs to the affected quantity: reducing shake is useful;
        # reducing stability is the erroneous relationship found in the trial.
        bad_effect = (r"(?:(?:影响|降低|减弱|削弱|不利于).{0,12}稳定"
                      r"|(?:增加|导致|造成|加重|增大).{0,12}(?:抖动|晃动))")
        if re.search(fast + r".{0,12}" + bad_effect, clause):
            if not re.search(fast + r".{0,5}(?:不会|不能|并不|不).{0,5}(?:影响|降低|减弱|削弱|导致|造成|增加|加重|增大)", clause):
                issues.add("shutter_stability_causality")
        ibis = r"(?:机身防抖|IBIS)"
        if re.search(ibis, clause, re.IGNORECASE):
            conditional = bool(re.search(r"(?:如果|若|如|仅在|确认).{0,12}(?:支持|具备|有|可用)", clause))
            absence = bool(re.search(r"(?:该机|本机|机身|相机).{0,6}(?:没有|不具备|不支持|无).{0,6}(?:机身防抖|防抖|IBIS)", clause, re.IGNORECASE))
            if absence and facts.ibis != "absent" and not re.search(r"如果|若|未知|未确认|不确定|不能确定|无法确定", clause):
                issues.add("ibis_capability_conflict")
            if (facts.ibis != "present" and not _negated(clause, ibis)
                    and not (conditional and facts.ibis == "unknown")):
                if re.search(r"(?:开启|打开|配合|利用|依赖|依靠|借助|具备|拥有|支持|带有|可).{0,10}" + ibis, clause, re.IGNORECASE):
                    issues.add("ibis_capability_conflict")
            if re.search(ibis + r".{0,12}(?:凝固|冻结|消除).{0,8}(?:主体|动作|运动)", clause, re.IGNORECASE) and not _negated(clause, r"(?:凝固|冻结|消除)"):
                issues.add("ibis_subject_motion_causality")
        if ("钨丝灯" in clause and re.search(r"保留|保持|维持|营造|增强", clause)
                and re.search(r"暖色|暖调|温暖", clause)
                and not _negated(clause, r"(?:保留|保持|维持|营造|增强)")):
            issues.add("white_balance_goal_conflict")
        if facts.declared_light is None and re.search(r"(?:现场|光源|灯光).{0,6}(?:是|为|属于).{0,6}钨丝灯", clause):
            if not re.search(r"如果|若|不能|无法|未确认|不一定", clause):
                issues.add("light_source_unconfirmed")
    return issues


def _correction(code: str, facts: PhotographyFacts) -> str:
    if code == "shutter_stability_causality":
        return "高速快门有助于减轻相机抖动和凝固主体运动；光线不足时需结合测光提高 ISO。"
    if code == "ibis_capability_conflict":
        return ("该机身不具备 IBIS；手持稳定需靠姿势、支撑和合适快门，镜头防抖仅在确认支持时使用。"
                if facts.ibis == "absent" else "目录确认该机身具备 IBIS；实际效果受镜头和姿势影响，不能代替运动所需快门。"
                if facts.ibis == "present" else "该机型机身防抖能力未确认；请按实际菜单核对，不依赖未经确认的防抖能力。")
    if code == "ibis_subject_motion_causality":
        return "机身防抖只补偿相机抖动，不能凝固主体运动；运动清晰度仍需足够快的快门。"
    return facts.white_balance_instruction + "；照片暖色不能确认光源种类，需现场试拍核对。"


def _correct_text(text: str, facts: PhotographyFacts) -> str:
    corrected = []
    for clause in _clauses(text):
        found = semantic_issues(clause, facts)
        if found:
            corrected.extend(_correction(code, facts).rstrip("。") for code in sorted(found))
        else:
            corrected.append(clause)
    return "；".join(dict.fromkeys(corrected)) + "。"


def reconcile_parameter_facts(recommendation: CameraRecommendation,
                               facts: PhotographyFacts) -> CameraRecommendation:
    if facts.device_type == "phone":
        return recommendation
    updates: dict[str, object] = {}
    codes: set[str] = set()
    for field in ("reasons", "risks", "adjustments"):
        texts = []
        for text in getattr(recommendation, field):
            found = semantic_issues(text, facts)
            codes.update(found)
            if found:
                texts.append(_correct_text(text, facts))
            else:
                texts.append(text)
        updates[field] = list(dict.fromkeys(texts))
    if facts.white_balance_goal != "unspecified" and recommendation.white_balance != facts.white_balance_instruction:
        updates["white_balance"] = facts.white_balance_instruction
        codes.add("white_balance_shared_goal")
    if codes:
        updates["validation_notes"] = list(dict.fromkeys([*recommendation.validation_notes,
            "摄影文字本地一致性修正：" + "、".join(sorted(codes)) + "；未校验到的文字仍需试拍核对。",
        ]))
        updates["confidence"] = min(recommendation.confidence, .75)
    return recommendation.model_copy(update=updates)


def _has_positive_symmetry(text: str) -> bool:
    return any(re.search(r"(?:左右|中轴|轴线|严格).{0,6}对称|对称(?:结构|构图)", clause)
               and not _negated(clause, r"对称")
               and not re.search(r"牺牲|打破|破坏|丧失|失去|减弱|放弃|区别|代价", clause)
               for clause in _clauses(text))


def _parallax_promise(text: str) -> bool:
    return bool(re.search(r"(?:推荐图|示意图|图中).{0,8}(?:已经|已|证明|确保|实现).{0,10}(?:消除|改善|减少).{0,8}(?:遮挡|视差|透视)", text))


def _descriptive_fields(proposal: CompositionProposal):
    yield "goal", proposal.goal
    for name in ("composition_intent", "framing_plan", "sketch", "storyboard"):
        model = getattr(proposal, name)
        if model is not None:
            for field, value in model.model_dump().items():
                if field not in {"elements", "layers"}:
                    if isinstance(value, str):
                        yield name + "." + field, value
                    elif field == "limitations":
                        for text in value:
                            yield name + ".limitations", text
                    elif field == "changes":
                        for change in value:
                            for text in change.values():
                                yield name + ".changes", text


def _sanitize_descriptions(proposal: CompositionProposal, facts: PhotographyFacts):
    """Close the same guard over visible nested prose without touching geometry."""
    notes, updates = [], {}

    def checked(text: str) -> str:
        codes = semantic_issues(text, facts)
        if codes:
            notes.append("已修正构图说明字段中的摄影关系：" + "、".join(sorted(codes)) + "。")
            # One bounded correction fits even the 100-character legacy fields;
            # do not put a long joined replacement into a validated short leaf.
            return _correction(sorted(codes)[0], facts)
        if _parallax_promise(text):
            notes.append("已去除说明字段中二维图已实现真实透视或遮挡改善的承诺。")
            return "二维图仅示意统一取景；透视与遮挡变化需现场观察、试拍核对。"
        if (facts.white_balance_goal != "unspecified" and re.search(r"白平衡|色温|暖色调模式", text)
                and facts.white_balance_instruction not in text):
            return facts.white_balance_instruction + "。"
        return text

    updates["goal"] = checked(proposal.goal)
    for name in ("composition_intent", "framing_plan", "sketch", "storyboard"):
        model = getattr(proposal, name)
        if model is None:
            continue
        fields = {}
        for field, value in model.model_dump().items():
            if field in {"elements", "layers", "focus_object_id", "reference_photo_id", "aspect",
                         "vertical_placement", "subject_scale", "camera_action",
                         "theme", "mood", "distance_relation", "render_basis", "layout_mode", "layout_engine"}:
                continue
            if isinstance(value, str):
                fields[field] = checked(value)
            elif field == "limitations":
                fields[field] = [checked(text) for text in value]
            elif field == "changes":
                fields[field] = [change.model_copy(update={key: checked(text)
                    for key, text in change.model_dump().items()}) for change in model.changes]
        updates[name] = model.model_copy(update=fields)
    return proposal.model_copy(update=updates), notes


def reconcile_composition_proposal(proposal: CompositionProposal,
                                    facts: PhotographyFacts) -> tuple[CompositionProposal, list[str]]:
    if facts.device_type == "phone":
        return proposal, []
    updates: dict[str, object] = {}
    notes: list[str] = []
    fields = ("actions", "reasons", "tradeoffs", "conditions", "limitations")
    all_text = " ".join([*(text for _, text in _descriptive_fields(proposal)),
                         *(text for field in fields for text in getattr(proposal, field))])
    positive_offset_text = " ".join(clause for clause in _clauses(all_text) if not _negated(clause, r"三分"))
    offset = bool(re.search(r"(?:左|右)(?:侧)?三分|(?:左|右)侧.{0,5}三分线", positive_offset_text))
    acknowledges_tradeoff = bool(re.search(r"(?:牺牲|打破|破坏|丧失|失去|减弱|放弃|不再|无法保持|不能兼顾).{0,12}(?:对称|中轴)", all_text))
    simultaneous_claim = bool(re.search(r"(?:三分.{0,20}(?:同时|且|并).{0,20}对称|对称.{0,20}(?:同时|且|并).{0,20}三分)", positive_offset_text))
    conflict = offset and _has_positive_symmetry(all_text) and (not acknowledges_tradeoff or simultaneous_claim)
    if proposal.composition_intent:
        conflict |= (proposal.composition_intent.placement in {"left", "right"} and _has_positive_symmetry(all_text)
                     and (not acknowledges_tradeoff or simultaneous_claim))
    if conflict:
        # Reset intent before local layout, not after drawing. The original
        # geometry is the only comparison baseline available without a new view.
        if proposal.composition_intent:
            updates["composition_intent"] = proposal.composition_intent.model_copy(update={
                "placement": "keep", "diagnosis": "保留原构图作为比较基准，先保护左右主要结构与连续纵深。"})
        updates["goal"] = "保留原构图作为比较基准，保护左右主要结构与连续纵深"
        # Legacy provider-owned geometry cannot be made consistent by editing
        # the prose alone. New intent boards are generated only after this fix.
        updates.update(storyboard=None, sketch=None, framing_plan=None)
        notes.append("已修正偏置三分与中轴对称的冲突；保留原取景作为比较基准，现场试拍再比较。")
    for field in fields:
        texts = []
        for text in getattr(proposal, field):
            found = semantic_issues(text, facts)
            if found:
                texts.append(_correct_text(text, facts))
                notes.append("已按共享摄影事实修正构图文字：" + "、".join(sorted(found)) + "。")
                continue
            if conflict and (re.search(r"三分|对称|左右.{0,5}平衡", text)):
                continue
            # Keep focus/framing clauses surrounding a white-balance directive.
            if facts.white_balance_goal != "unspecified" and re.search(r"白平衡|色温|暖色调模式", text):
                if facts.white_balance_instruction in text:
                    texts.append(text)
                    continue
                clauses = [clause for clause in _clauses(text) if not re.search(r"白平衡|色温|暖色调模式|保留暖色|维持.*氛围", clause)]
                texts.append("；".join([*clauses, facts.white_balance_instruction]) + "。")
                continue
            if re.search(r"侧移|平移机位|向[左右]移动", text) and re.search(r"遮挡|视差|透视", text):
                if not re.search(r"现场|试拍|观察|无法|不能|待确认|可能", text):
                    text = "现场小幅侧移并观察、试拍，核对遮挡与透视变化；二维推荐图不能证明该变化。"
                    notes.append("真实侧移的遮挡与透视变化已标为现场试拍条件。")
            if _parallax_promise(text):
                text = "二维推荐图只表示统一取景变换；侧移后的透视与遮挡需现场观察、试拍核对。"
                notes.append("已去除二维图已经实现真实视差改善的无依据承诺。")
            texts.append(text)
        updates[field] = list(dict.fromkeys(texts))
    if conflict:
        updates["actions"] = ["先保留原取景，检查左右主要结构与拱门递进关系。", *updates["actions"]]
        updates["reasons"] = [*updates["reasons"], "比较原有居中或中轴取景与偏置三分：前者利于秩序和左右呼应，后者可强调方向，但可能牺牲严格中轴对称；本方案先保留原构图。"]
    defaults = {
        "actions": "保留当前取景并现场试拍，核对主体关键边缘。",
        "reasons": "先以原取景为比较基准，避免展示互相冲突的构图要求。",
        "tradeoffs": "保留原取景可能保留原有背景干扰，调整的收益需另行试拍比较。",
        "conditions": "原图可见范围内的主要结构需能可靠辨认；拍摄前核对现场条件。",
        "limitations": "本地规则只检查部分明确关系，未覆盖的文字仍需现场验证。",
    }
    for field in fields:
        if not updates[field]:
            updates[field] = [defaults[field]]
    result, descriptive_notes = _sanitize_descriptions(proposal.model_copy(update=updates), facts)
    return result, list(dict.fromkeys([*notes, *descriptive_notes]))


def reconcile_composition_facts(advice: CompositionAdvice,
                                 facts: PhotographyFacts) -> CompositionAdvice:
    proposals, notes = [], list(advice.notes)
    for proposal in advice.proposals:
        checked, messages = reconcile_composition_proposal(proposal, facts)
        proposals.append(checked)
        notes.extend(messages)
    return advice.model_copy(update={"proposals": proposals, "notes": list(dict.fromkeys(notes))})


def preserve_continuous_framing(advice: CompositionAdvice,
                                 facts: PhotographyFacts) -> CompositionAdvice:
    """Match continuous source geometry before the solver computes its board.

    This is an explicit conservative rendering mode, not evidence that a new
    viewpoint was achieved. No missing intent or source geometry is invented.
    """
    proposals = []
    for proposal in advice.proposals:
        if proposal.composition_intent is None:
            proposals.append(proposal)
            continue
        reflection = facts.preserve_reflection
        diagnosis = ("保留原取景中山峰、水岸与倒影的关联和可见范围，以原有镜像关系作为比较基准。"
                     if reflection else "保留原取景中连续结构的相对顺序、消失方向与两侧可见范围，以原构图作为比较基准。")
        intent = proposal.composition_intent.model_copy(update={
            "placement": "keep", "vertical_placement": "keep", "subject_scale": "keep", "aspect": "keep",
            "diagnosis": diagnosis,
        })
        # Movement, scaling and exact placement claims cannot survive a keep
        # layout. Preserve other concrete checks, then explain the limitation.
        def compatible(text: str) -> bool:
            return not bool(re.search(r"三分|侧移|平移|靠近|后退|前移|退后|改变.*机位|调整.*地平线|"
                                      r"置于|放在|移到|扩大|放大|缩小|增大|降低机位|抬高机位", text))
        reasons = [text for text in proposal.reasons if compatible(text)]
        reasons.append(diagnosis)
        reasons.append("比较保留原构图与三分：偏移地平线或纵深轴线可能牺牲镜像平衡或两侧呼应；本推荐图保留原取景，不强行三分。")
        actions = ["先保留原照片的取景、比例与可见边界，检查主要结构的连续性和原有截断。",
                   *[text for text in proposal.actions if compatible(text)]]
        limitations = [*[text for text in proposal.limitations if compatible(text)],
            "本图保留原取景作为比较基准；未模拟新机位或恢复画外内容，真实透视和遮挡变化需现场试拍。"]
        proposals.append(proposal.model_copy(update={
            "goal": "保留连续场景的整体关系与原取景，比较调整的代价",
            "composition_intent": intent, "actions": list(dict.fromkeys(actions)),
            "reasons": list(dict.fromkeys(reasons)),
            "conditions": [text for text in proposal.conditions if compatible(text)] or
                ["保留原取景的比较基准，现场核对主要结构与边缘可见范围。"],
            "tradeoffs": [text for text in proposal.tradeoffs if compatible(text)] or
                ["保留原取景也会保留原有背景与截断；其他机位的收益需另行试拍比较。"],
            "limitations": list(dict.fromkeys(limitations))[:6],
        }))
    return advice.model_copy(update={"proposals": proposals, "notes": list(dict.fromkeys([
        *advice.notes, "连续场景使用保留原取景的结构表达；文字与本图均不承诺独立移动山峰、倒影或建筑构件。",
    ]))})
