"""Local display conversion only; never modify stored answers or invent observations."""

from vision_lab_tool.models import VisibleObject

OBJECT_NAMES = {
    "person": "人物",
    "people": "人群",
    "man": "男子",
    "woman": "女子",
    "child": "儿童",
    "bird": "鸟",
    "cat": "猫",
    "dog": "狗",
    "bicycle": "自行车",
    "car": "汽车",
    "tree": "树",
    "building": "建筑",
    "flower": "花",
    "mountain": "山",
    "waterfall": "瀑布",
    "window": "窗户",
}
ENVIRONMENTS = {"indoor": "室内", "outdoor": "室外", "mixed": "室内外混合", "unknown": "无法确定"}
BACKLIGHT = {"yes": "模型判断有逆光", "no": "模型判断无逆光", "unknown": "无法确定"}
ACTIONS = {
    "crop": "裁切现有照片",
    "camera_position": "调整机位",
    "focal_length": "改变焦距",
    "reshoot": "重新拍摄",
}


def display_label(label: str) -> str:
    translated = OBJECT_NAMES.get(label.strip().casefold())
    return f"{translated}（{label}）" if translated else label


def reported(values: list[str] | None) -> list[str]:
    return list(values) if values else ["未报告"]


def box_position(box: list[float] | None) -> str:
    if box is None:
        return "未提供位置框"
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    horizontal = "左侧" if x < 1 / 3 else "右侧" if x > 2 / 3 else "中间"
    vertical = "上部" if y < 1 / 3 else "下部" if y > 2 / 3 else "中部"
    return f"框中心：画面{horizontal}、{vertical}"


def overlay_objects(observation: dict) -> list[VisibleObject]:
    return [
        VisibleObject.model_validate(obj).model_copy(update={"label": display_label(obj["label"])})
        for obj in observation["objects"]
    ]


def observation_sections(observation: dict) -> list[tuple[str, list[str]]]:
    objects = observation["objects"]
    names = {obj["object_id"]: display_label(obj["label"]) for obj in objects}

    def subject_name(value: str) -> str:
        return f"{names[value]}（编号 {value}）" if value in names else value

    main_id = observation["main_subject_id"]
    if not observation["main_subject_determined"]:
        main = "主要主体：模型未确认"
        if main_id is not None:
            main += f"；返回的主体编号：{subject_name(main_id)}"
    else:
        main = (
            f"主要主体：{subject_name(main_id)}"
            if main_id is not None
            else "主要主体：模型称已确认，但未提供主体编号"
        )
    subject_lines = [main]
    if observation["subject_candidates"]:
        subject_lines.append(
            "主体候选：" + "、".join(map(subject_name, observation["subject_candidates"]))
        )
    for obj in objects:
        confidence = (
            "自报可信度未知" if obj["confidence"] is None else f"自报可信度 {obj['confidence']:.0%}"
        )
        subject_lines.append(
            f"{display_label(obj['label'])}（编号 {obj['object_id']}） · "
            f"{box_position(obj['bbox'])} · {confidence}"
        )
    if not objects:
        subject_lines.append("未报告可见对象")
    light = observation["light"]
    return [
        (
            "场景",
            [f"环境：{ENVIRONMENTS[observation['environment']]}"]
            + [
                f"{scene['label']}：{scene['evidence'] or '未填写观察依据'}"
                for scene in observation["scene_labels"]
            ],
        ),
        ("主体", subject_lines),
        (
            "光线与明暗",
            [
                "逆光：" + BACKLIGHT[light["backlight"]],
                "明暗关系：" + (light["brightness_relations"] or "未填写"),
            ]
            + reported(light["phenomena"]),
        ),
        ("构图线索", reported(observation["composition_clues"])),
        ("可见运动线索", reported(observation["motion"]["visible_clues"])),
        ("运动推测（不是已确认事实）", reported(observation["motion"]["inferences"])),
        ("不确定信息", reported(observation["uncertainties"])),
        ("需要你补充的问题", reported(observation["clarification_questions"])),
    ]


def proposal_sections(proposal: dict, number: int) -> tuple[str, list[tuple[str, list[str]]]]:
    return f"方案 {number} · {ACTIONS[proposal['action_type']]}", [
        ("目标", [proposal["goal"] or "未填写"]),
        ("怎么做", reported(proposal["actions"])),
        ("理由", reported(proposal["reasons"])),
        ("取舍", reported(proposal["tradeoffs"])),
        ("适用条件", reported(proposal["conditions"])),
        ("限制", reported(proposal["limitations"])),
        (
            "可选参数",
            list(proposal["parameters"]) if proposal["parameters"] else ["未提供；不补猜拍摄参数"],
        ),
    ]
