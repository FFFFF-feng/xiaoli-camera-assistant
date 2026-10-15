from __future__ import annotations

import re

from camera_assistant.models import EnvironmentContext, SceneAnalysis, UserRequest

ENVIRONMENT_ANALYSIS_PROMPT = """environment 保留画面环境的兼容标签；同时填写 environment_context。
content_environment 描述画面中的室内/室外/混合内容，不代表相机所在位置。
shooting_location 只采用用户已明确提供的拍摄位置，否则 unknown，
shooting_location_source 只可为 user 或 unknown。窗框、窗景、倒影本身不能确认相机在室内。
relationship 描述同环境、隔窗观看、混合画面或反射关系；窗框和室外风景同时可见时，
可写 content_environment=mixed、relationship=through_window，并明确拍摄位置未确认。
evidence 只写观察到的内容；uncertainties 保留无法判断的拍摄位置和隔窗/反射条件。
不得仅凭 indoor/outdoor 标签推断现场照度、光线强弱、曝光参数或曝光是否正确。
照片明暗是记录外观，不是绝对照度测量；室内外内容可能有不同亮度，仍需现场测光与试拍。"""

_ENVIRONMENT_LABELS = {
    "indoor": "室内",
    "outdoor": "室外",
    "mixed": "室内外混合",
    "unknown": "未确认",
}
_RELATIONSHIP_LABELS = {
    "same_environment": "用户拍摄位置与画面环境相同",
    "through_window": "画面呈现隔窗观看关系",
    "mixed_view": "画面同时呈现室内与室外内容",
    "reflection": "画面含反射或倒影，反射内容与拍摄位置分开判断",
    "unknown": "画面内容与拍摄位置的关系未确认",
}
_UNKNOWN_LOCATION = "画面环境不等于相机所在位置；拍摄位置未确认。"
_NO_LIGHT_INFERENCE = (
    "画面环境标签与参考照片明暗不代表现场绝对照度；"
    "不得仅凭室内/室外标签推断曝光，应以现场测光、直方图及试拍检查。"
)


def normalize_scene_environment(scene: SceneAnalysis, request: UserRequest) -> SceneAnalysis:
    """Retain the legacy tag and record relationships as observations, not site facts."""
    old = scene.environment_context
    visual_evidence = [
        *scene.recognition_evidence,
        *scene.composition_clues,
        *old.evidence,
        *(f"{obj.label} ({obj.query})" for obj in scene.objects),
    ]
    visual_text = " ".join(visual_evidence).lower()
    content = old.content_environment
    if content == "unknown":
        content = _legacy_content(scene.environment)
    relationship = old.relationship

    has_window = _has_visible_window_frame(visual_text)
    has_outdoor = content in {"outdoor", "mixed"} or bool(
        re.search(r"室外|户外|窗外|庭院|天空|山峰|山脉|outdoor|landscape view", visual_text)
    )
    if has_window and has_outdoor:
        content = "mixed"
        relationship = "through_window"
    elif content == "mixed" and relationship == "unknown":
        relationship = "mixed_view"

    location = request.shooting_location
    # Natural language is accepted only for a narrow, explicit user statement.
    # Merely requesting a window composition supplies no camera-position fact.
    if location == "unknown":
        location = _explicit_user_location(request.intent)
    if relationship == "same_environment" and (
        location == "unknown" or content not in {"indoor", "outdoor"} or location != content
    ):
        relationship = "unknown"

    uncertainties = list(old.uncertainties)
    has_boundary = relationship in {"through_window", "mixed_view", "reflection"}
    if location == "unknown" and has_boundary:
        uncertainties.append(_UNKNOWN_LOCATION)
    if has_boundary:
        uncertainties.append(_NO_LIGHT_INFERENCE)
    if relationship == "through_window":
        uncertainties.append("玻璃是否存在、是否打开，以及反光或透光影响需现场确认。")
    if location != "unknown":
        uncertainties = [item for item in uncertainties if item != _UNKNOWN_LOCATION]

    context = EnvironmentContext(
        shooting_location=location,
        shooting_location_source="user" if location != "unknown" else "unknown",
        content_environment=content,
        relationship=relationship,
        evidence=list(dict.fromkeys(visual_evidence)),
        uncertainties=list(dict.fromkeys(uncertainties)),
    )
    combined_uncertainties = list(dict.fromkeys([*scene.uncertainties, *context.uncertainties]))
    if location != "unknown":
        combined_uncertainties = [item for item in combined_uncertainties if item != _UNKNOWN_LOCATION]
    return scene.model_copy(update={
        "environment_context": context,
        "uncertainties": combined_uncertainties,
    })


def environment_display_lines(scene: SceneAnalysis) -> list[str]:
    context = scene.environment_context
    source = "（用户确认）" if context.shooting_location_source == "user" else ""
    relationship = _RELATIONSHIP_LABELS[context.relationship]
    if context.relationship == "through_window" and _has_visible_window_frame(
        " ".join(context.evidence).lower()
    ):
        relationship = "画面包含窗框和室外风景，呈现隔窗观看关系"
    return [
        f"画面内容：{_ENVIRONMENT_LABELS[context.content_environment]}（视觉线索）",
        f"拍摄位置：{_ENVIRONMENT_LABELS[context.shooting_location]}{source}",
        relationship,
        *context.uncertainties,
    ]


def environment_advice_constraints(scene: SceneAnalysis) -> str:
    context = scene.environment_context
    lines = environment_display_lines(scene)
    if context.shooting_location == "unknown":
        lines.append("拍摄位置未确认，不推定用户在室内或室外。")
    return "\n".join([
        "环境条件与边界：",
        *dict.fromkeys(lines),
        _NO_LIGHT_INFERENCE,
        "分别检查近处与远处内容的高光/暗部；参数起点须经过现场测光和试拍。",
    ])


def _legacy_content(value: str) -> str:
    text = value.lower().strip()
    if text in {"mixed", "室内外", "室内外混合", "indoor/outdoor", "indoor and outdoor"}:
        return "mixed"
    if text in {"indoor", "室内"}:
        return "indoor"
    if text in {"outdoor", "室外", "户外"}:
        return "outdoor"
    return "unknown"


def _explicit_user_location(intent: str) -> str:
    pattern = re.compile(
        r"(?:我(?:现在)?(?:正)?(?:站|坐)?(?:在|位于)|"
        r"相机(?:现在)?(?:在|位于)|拍摄位置(?:为|是|在))\s*(室内|室外|屋内|户外)"
    )
    found: list[str] = []
    for match in pattern.finditer(intent):
        prefix = intent[max(0, match.start() - 8):match.start()]
        suffix = intent[match.end():match.end() + 10]
        if re.match(r"\s*(?:吗|呢|还是|或者|或是|可能|大概|也许|拍(?:摄|照)?(?:吗|呢))", suffix):
            continue
        if re.search(r"如果|假如|假设|可能|也许|是否|不确定|不知道|不清楚|未确认", prefix + suffix):
            continue
        if re.match(r"[\s，,]*[？?]", suffix):
            continue
        found.append("indoor" if match[1] in {"室内", "屋内"} else "outdoor")
    return found[0] if len(set(found)) == 1 else "unknown"


def _has_visible_window_frame(text: str) -> bool:
    for match in re.finditer(r"窗框|窗台|window frame|window sill", text):
        prefix = text[max(0, match.start() - 16):match.start()]
        suffix = text[match.end():match.end() + 8]
        if re.search(r"(?:没有|未见|看不到|不可见|无)(?:完整的|明显的|任何)?$|no (?:visible )?$", prefix):
            continue
        if re.match(r"(?:不在画面|不可见|未出现| is not visible)", suffix):
            continue
        return True
    return False
