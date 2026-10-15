"""Conservative checks for the concrete contradictions found in real trials.

These checks reject explicit, measurable contradictions; they are not a general
natural-language truth evaluator and do not certify unflagged model prose.
"""
from __future__ import annotations

import math
import re

from camera_assistant.composition_models import CompositionProposal
from camera_assistant.models import CameraProfile, CameraRecommendation, SceneAnalysis, UserRequest
from camera_assistant.services.advice_review import review_operations

SUBJECT = r"(?:主体|猫|人物|人像|瀑布|subject)"
DISTANCE = re.compile(r"\d+(?:\.\d+)?(?:\s*[-–—至]\s*\d+(?:\.\d+)?)?\s*(?:厘米|米|cm|m)(?!m)", re.IGNORECASE)


def _unmeasured_distance(text: str) -> bool:
    return bool(DISTANCE.search(text) and re.search(r"拍摄距离|机位|移动|后退|靠近|相距|距离", text)
                and not re.search(r"不(?:要|得|应)|不能|不可", text))


def _wrong_underexposure_fix(text: str) -> bool:
    if re.search(r"(?:光圈过小|缩小光圈)(?:而|会|直接|就)?(?:导致|造成)(?:过曝|过亮)", text):
        return True
    if re.search(r"(?:降低|提高|增加|减少)\s*ISO.{0,18}(?:减少|增加|降低|提高)(?:进光量|入射光量)", text, re.IGNORECASE):
        return True
    if not re.search(r"低\s*ISO|降低\s*ISO|负.{0,5}(?:补偿|EV)", text, re.IGNORECASE):
        return False
    return bool(re.search(r"(?:避免|防止|改善|解决).{0,8}(?:欠曝|偏暗)|否则.{0,12}欠曝", text)
                and not re.search(r"不(?:能|会|应).{0,12}(?:避免|解决|改善).{0,8}欠曝", text))


def _wrong_stop_count(text: str, request: UserRequest) -> bool:
    # Mixed exposure instructions do not identify which control a stop claim describes.
    if re.search(r"ISO|快门|曝光补偿", text, re.IGNORECASE):
        return False
    claims = re.findall(r"(?:大|小|增加|减少)\s*([0-9.]+|一|二|两|三|四)\s*(?:档|挡)", text)
    apertures = [float(value) for value in re.findall(r"f\s*/\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)]
    if not claims or not apertures:
        return False
    if len(apertures) < 2:
        if request.max_aperture is None or "最大光圈" not in text:
            return False
        apertures.append(request.max_aperture)
    if any(value <= 0 for value in apertures[:2]):
        return True
    actual = abs(2 * math.log2(apertures[0] / apertures[1]))
    words = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4}
    return any(abs((words[value] if value in words else float(value)) - actual) > .2
               for value in claims)


def composition_issue(proposal: CompositionProposal, request: UserRequest) -> str | None:
    instructions = " ".join(proposal.actions)
    statements = [*proposal.actions, *proposal.reasons, *proposal.tradeoffs,
                  *proposal.conditions, *proposal.limitations]
    focal_values = [float(value) for value in re.findall(r"(\d+(?:\.\d+)?)\s*mm", instructions, re.IGNORECASE)]
    changes_focal = bool(request.focal_length_mm and any(
        abs(value - request.focal_length_mm) > .01 for value in focal_values))
    positive_instructions = re.sub(r"(?:不要|不应|不得|不可|不能|避免)[^，。;；]*", "", instructions)
    moving = bool(re.search(r"后退|远离|退后|靠近|前移|向前|向后", positive_instructions))
    if not changes_focal:
        for text in statements:
            text = re.sub(r"(?:不要|不应|不得|不可|不能|避免)[^，。;；]*", "", text)
            if re.search(r"(?:后退|远离|退后).{0,40}" + SUBJECT + r".{0,20}(?:更大|放大|增大)", text):
                return "同焦段后退与主体放大解释冲突，已移除该方案。"
            if re.search(r"(?:后退|远离|退后).{0,20}放大" + SUBJECT, text):
                return "同焦段后退与主体放大解释冲突，已移除该方案。"
        if re.search(r"后退|远离|退后", positive_instructions) and any(
            re.search(SUBJECT + r".{0,20}(?:更大|放大|增大)", reason)
            and not re.search(r"不(?:会|能)|不能", reason)
            for reason in proposal.reasons
        ):
            return "同焦段后退与主体放大解释冲突，已移除该方案。"
    if changes_focal and not moving and request.focal_length_mm:
        larger = any(value > request.focal_length_mm for value in focal_values)
        if larger and any(re.search(r"(?:缩小|减小|减少).{0,15}" + SUBJECT + r"|" + SUBJECT + r".{0,20}(?:缩小|减小)", text)
                          for text in statements):
            return "固定机位增加焦段与主体变小解释冲突，已移除该方案。"
    if any(_wrong_stop_count(text, request) for text in statements):
        return "光圈档数与数值不一致，已移除该方案。"
    if any(_wrong_underexposure_fix(text) for text in statements):
        return "曝光调整方向解释冲突，已移除该方案。"
    if any(_unmeasured_distance(text) for text in proposal.actions):
        return "缺少距离测量与最近对焦条件，已移除给定精确距离的方案。"
    if request.max_aperture and any(
        float(value) < request.max_aperture
        for text in proposal.actions if not re.search(r"不(?:要|得|应)|不能", text)
        for value in re.findall(r"f\s*/\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    ):
        return "构图操作要求的光圈超出当前镜头能力，已移除该方案。"
    return None


def screen_parameter_advice(recommendation: CameraRecommendation,
                            request: UserRequest, *,
                            scene: SceneAnalysis | None = None,
                            camera: CameraProfile | None = None) -> CameraRecommendation:
    updates = {}
    removed = 0
    for field in ("reasons", "risks", "adjustments"):
        texts = getattr(recommendation, field)
        kept = [text for text in texts if not _wrong_underexposure_fix(text)
                and not _unmeasured_distance(text) and not _wrong_stop_count(text, request)
                and not _unsupported_physics(text, request)]
        removed += len(texts) - len(kept)
        updates[field] = kept
    updates["safety_notes"] = list(recommendation.safety_notes)
    if removed:
        updates["safety_notes"].append(
            "已移除曝光、景深、防抖、当前设置或未测量距离的无依据说明；未命中筛查不代表文字已验证。"
        )
        updates["confidence"] = min(recommendation.confidence, .6)
    reviewed, notes = review_operations(
        recommendation.candidate_operations, request, scene, camera, recommendation,
    )
    updates["reviewed_operations"] = reviewed
    updates["safety_notes"] = list(dict.fromkeys([*updates["safety_notes"], *notes]))
    return recommendation.model_copy(update=updates)


def _unsupported_physics(text: str, request: UserRequest) -> bool:
    """Extra legacy-prose triage. New operations use the independent rule registry."""
    if re.search(r"不(?:会|能|直接)|并非|不是|不等于", text):
        return False
    if (re.search(r"ISO|快门|曝光时间", text, re.IGNORECASE)
            and re.search(r"景深.{0,10}(?:减|变|浅)|(?:减小|改变|降低).{0,4}景深", text)
            and not re.search(r"同时.{0,8}(?:光圈|焦距|距离)", text)):
        # No optical DOF consequence can be established from only shutter/ISO.
        return True
    if re.search(r"电子快门|电子前帘|EFCS", text, re.IGNORECASE) and re.search(r"机身防抖|IBIS|补偿.{0,8}(?:手持|手抖)|手持.{0,8}补偿", text, re.IGNORECASE):
        return True
    if re.search(r"当前光圈|目前光圈|现有光圈", text):
        current = getattr(request, "current_settings", None)
        if current is None or getattr(current, "aperture", None) is None:
            return True
    # Incident light is an optical quantity; ISO cannot change it, whatever its value.
    return bool(re.search(r"ISO", text, re.IGNORECASE)
                and re.search(r"(?:降低|减少|增加|提高).{0,8}(?:进光量|入射光量)", text))
