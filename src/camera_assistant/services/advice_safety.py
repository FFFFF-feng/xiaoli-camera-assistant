"""Conservative checks for the concrete contradictions found in real trials.

These checks reject explicit, measurable contradictions; they are not a general
natural-language truth evaluator and do not certify unflagged model prose.
"""
from __future__ import annotations

import math
import re

from camera_assistant.composition_models import CompositionProposal
from camera_assistant.models import CameraRecommendation, UserRequest

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


def unconfirmed_phone_controls(text: str, request: UserRequest) -> bool:
    if request.device_type != "phone" or (
        request.phone_capture_mode == "pro" and request.phone_pro_controls_confirmed
    ):
        return False
    return bool(re.search(r"(?:快门.{0,8}\d+\s*/\s*\d+|ISO\s*\d+|f\s*/\s*\d)", text, re.IGNORECASE)
                and not re.search(r"不(?:要|能|应)|不可|未确认", text))


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
    if any(re.search(r"(?:机位|身体|向左|向右|侧移|后退|靠近).{0,15}(?:移动|移|退|进).{0,12}(?:画面|画幅).{0,8}(?:宽|高|%|分之)", text)
           or re.search(r"(?:机位|身体).{0,10}(?:移动|侧移).{0,12}(?:\d+\s*/\s*\d+|\d+%|[一二三]分之[一二]).{0,6}(?:画面|画幅)", text)
           or re.search(r"(?:侧移|移动|后退|靠近).{0,16}(?:画面|画幅)(?:宽|高).{0,10}\d+\s*%", text)
           for text in statements):
        return "不能用画面尺寸代替身体移动距离，已移除该方案。"
    if any(unconfirmed_phone_controls(text, request) for text in statements):
        return "当前手机模式未确认手动曝光能力，已移除指定手动参数的构图方案。"
    if request.max_aperture and any(
        float(value) < request.max_aperture
        for text in proposal.actions if not re.search(r"不(?:要|得|应)|不能", text)
        for value in re.findall(r"f\s*/\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    ):
        return "构图操作要求的光圈超出当前镜头能力，已移除该方案。"
    return None


def screen_parameter_advice(recommendation: CameraRecommendation,
                            request: UserRequest) -> CameraRecommendation:
    updates = {}
    removed = 0
    for field in ("reasons", "risks", "adjustments"):
        texts = getattr(recommendation, field)
        kept = [text for text in texts if not _wrong_underexposure_fix(text)
                and not _unmeasured_distance(text) and not _wrong_stop_count(text, request)]
        removed += len(texts) - len(kept)
        updates[field] = kept
    updates["safety_notes"] = []
    if removed:
        updates["safety_notes"] = [
            "已移除包含曝光因果矛盾、光圈档数错误或未测量精确距离的模型说明；参数仍须试拍验证。"
        ]
        updates["confidence"] = min(recommendation.confidence, .6)
    return recommendation.model_copy(update=updates)
