import copy
import json

from vision_lab_tool.adapters import mock_answer
from vision_lab_tool.prompts import build_prompt


def test_readable_view_preserves_original_and_distinguishes_unknown_from_no():
    from vision_lab_tool.presentation import observation_sections, overlay_objects

    observation = json.loads(mock_answer("correct", "recognition"))
    observation["objects"][0]["label"] = "person"
    observation["objects"][0]["confidence"] = 0
    observation["objects"][0]["bbox"] = None
    observation["light"]["backlight"] = "unknown"
    observation["environment"] = "unknown"
    observation["motion"]["visible_clues"] = []
    observation["motion"]["inferences"] = ["可能正在行走"]
    observation["subject_candidates"] = [observation["objects"][0]["object_id"], "unmapped label"]
    original = copy.deepcopy(observation)
    sections = dict(observation_sections(observation))
    assert "环境：无法确定" in sections["场景"]
    assert any("人物（person）" in line for line in sections["主体"])
    assert any("未提供位置框" in line and "0%" in line for line in sections["主体"])
    assert any("unmapped label" in line for line in sections["主体"])
    assert "逆光：无法确定" in sections["光线与明暗"]
    assert sections["可见运动线索"] == ["未报告"]
    assert sections["运动推测（不是已确认事实）"] == ["可能正在行走"]
    observation["light"]["backlight"] = "no"
    assert "逆光：模型判断无逆光" in dict(observation_sections(observation))["光线与明暗"]
    observation["light"]["backlight"] = "unknown"
    objects = overlay_objects(observation)
    assert objects[0].label == "人物（person）"
    assert objects[0].object_id == original["objects"][0]["object_id"]
    assert observation == original


def test_advice_view_exposes_actions_tradeoffs_conditions_and_unknown_parameters():
    from vision_lab_tool.presentation import proposal_sections

    advice = json.loads(mock_answer("correct", "advice"))
    proposal = advice["proposals"][0]
    proposal["parameters"] = None
    original = copy.deepcopy(proposal)
    title, sections = proposal_sections(proposal, 1)
    assert title == "方案 1 · 裁切现有照片"
    lines = dict(sections)
    for field, label in [
        ("actions", "怎么做"),
        ("reasons", "理由"),
        ("tradeoffs", "取舍"),
        ("conditions", "适用条件"),
        ("limitations", "限制"),
    ]:
        assert lines[label] == (proposal[field] or ["未报告"])
    assert lines["可选参数"] == ["未提供；不补猜拍摄参数"]
    assert proposal == original


def test_future_prompts_request_chinese_values_without_changing_schema_or_mode_isolation():
    for mode in ("recognition", "advice"):
        prompt = build_prompt(mode, "旧版自定义模板", {"goal": "敏感目标"})
        assert "描述性文本请使用简体中文" in prompt
        assert "JSON 字段名、枚举值和主体编号保持 schema 要求" in prompt
        assert '"backlight"' in prompt and '"unknown"' in prompt
        assert ("敏感目标" in prompt) == (mode == "advice")
