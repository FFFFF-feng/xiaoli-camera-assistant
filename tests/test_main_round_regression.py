"""Saved real evidence exercises current main-pipeline audit, with zero model calls.

These checks address specified factual/control regressions. They do not score the
overall photographic usefulness or accuracy of ten model-generated suggestions.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "main_round_support", ROOT / "scripts/main_round_support.py")
assert SPEC and SPEC.loader
SUPPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPPORT)


@pytest.fixture(scope="module")
def replay(tmp_path_factory):
    if not (SUPPORT.BASELINE / "preflight.json").exists():
        pytest.skip("本地真实测试证据目录未提供；不可生成替代事实样本")
    output = tmp_path_factory.mktemp("main_round") / "replay"
    summary = SUPPORT.run_round(baseline=SUPPORT.BASELINE, output=output,
                                cases=[f"P{number:02}" for number in range(1, 11)], live=False)
    return output, summary


def result(replay, sample):
    return SUPPORT.read_json(replay[0] / f"{sample}-pipeline.json")


def parameter_text(value):
    recommendation = value["recommendation"]
    return "\n".join(recommendation[field][index]
                     for field in ("reasons", "risks", "adjustments")
                     for index in range(len(recommendation[field])))


def test_replay_uses_original_images_and_does_not_publish_knowledge(replay):
    output, summary = replay
    assert summary["completed"] == 10
    assert all(trial["returned"] for trial in summary["trials"])
    assert summary["real_model_calls"] == 0
    assert summary["returned_json_count"] == 24
    assert summary["failure_categories"] == {"connection": 4, "timeout": 2}
    assert all(trial["stages"]["vision"]["sent_bytes_match_baseline"]
               for trial in summary["trials"])
    assert all(not trial["parameter_hits"] and not trial["composition_hits"]
               for trial in summary["trials"])
    postflight = SUPPORT.read_json(output / "postflight.json")
    assert postflight["source_database_logically_unchanged"]
    assert not postflight["knowledge_publication_simulated"]


@pytest.mark.parametrize("sample", ["P02", "P08", "P10"])
def test_saved_m_fixed_iso_cannot_use_compensation_as_exposure_action(replay, sample):
    value = result(replay, sample)
    rec = value["recommendation"]
    assert rec["exposure_state"]["mode"] == "M"
    assert rec["exposure_state"]["iso_control"] == "manual"
    assert "不适用" in rec["exposure_compensation"]
    # Specific real failures must disappear from all explanatory sections, not only EV.
    old = SUPPORT.read_json(SUPPORT.BASELINE / f"{sample}-parameters-structured.json")
    bad = [line for field in ("reasons", "adjustments") for line in old[field]
           if "曝光补偿" in line]
    assert bad, "The saved fixture must reproduce the reported compensation error"
    assert all(line not in parameter_text(value) for line in bad)
    assert any(word in "\n".join(rec["adjustments"])
               for word in ("快门", "曝光时间", "光圈", "ISO"))


def test_saved_dof_and_iso_physics_errors_do_not_survive(replay):
    old_p03 = SUPPORT.read_json(SUPPORT.BASELINE / "P03-parameters-structured.json")
    bad_depth = next(line for line in old_p03["adjustments"] if "减小景深" in line)
    assert bad_depth not in parameter_text(result(replay, "P03"))
    old_p10 = SUPPORT.read_json(SUPPORT.BASELINE / "P10-parameters-structured.json")
    bad_iso = next(line for line in old_p10["reasons"] if "降低进光量" in line)
    assert bad_iso not in parameter_text(result(replay, "P10"))


@pytest.mark.parametrize("sample", ["P05", "P07"])
def test_natural_bird_and_cyclist_requests_select_complete_saved_targets(replay, sample):
    localization = result(replay, sample)["localization"]
    assert localization["selection"]["status"] == "selected"
    assert localization["selection"]["selected_ids"]
    assert localization["queries"]["task_scope"]["status"] == "known"
    assert not localization["queries"]["task_scope"]["missing_semantic_units"]


def test_multi_instance_and_reflection_evidence_stays_conservative(replay):
    for sample in ("P02", "P06", "P09"):
        localization = result(replay, sample)["localization"]
        assert localization["selection"]["status"] != "selected"
        assert not localization["selection"]["selected_ids"]
    old = SUPPORT.read_json(SUPPORT.BASELINE / "P09-composition-structured.json")
    bad = old["proposals"][0]
    proposals = result(replay, "P09")["composition"]["proposals"]
    assert all(proposal["goal"] != bad["goal"] for proposal in proposals)
    final_text = "\n".join(line for proposal in proposals
                           for field in ("actions", "reasons", "tradeoffs", "conditions", "limitations")
                           for line in proposal[field])
    assert "电子快门补偿" not in final_text
    assert "需依赖机身防抖" not in final_text


def test_verified_aperture_capability_is_not_current_setting(replay):
    value = result(replay, "P01")
    text = "\n".join(line for proposal in value["composition"]["proposals"]
                     for field in ("actions", "reasons", "conditions", "limitations")
                     for line in proposal[field])
    assert "当前光圈" not in text
    state = value["recommendation"]["exposure_state"]
    assert not (state["current_settings"] or {}).get("aperture")


def test_successful_stages_and_sound_crop_survive_other_stage_failures(replay):
    for sample in ("P04", "P05"):
        value = result(replay, sample)
        assert value["recommendation"]["shooting_mode"] == "未生成"
        assert value["composition"]["proposals"]
    p01 = result(replay, "P01")["recommendation"]
    assert p01["exposure_state"]["mode"] == "Av"
    assert p01["reasons"]
    p10 = result(replay, "P10")
    assert any(proposal["crop_bbox"] for proposal in p10["composition"]["proposals"])


@pytest.fixture(scope="module")
def live_reaudit(tmp_path_factory):
    saved = ROOT / "data/history/main-fix-live-20261014-125300"
    if not (saved / "summary.json").exists():
        pytest.skip("本轮真实回答未随源码分发；不能构造假模型回答补足")
    output = tmp_path_factory.mktemp("saved_live_reaudit") / "replay"
    summary = SUPPORT.run_round(baseline=saved, output=output,
                                cases=[f"P{number:02}" for number in range(1, 11)], live=False)
    return output, summary


def test_live_optional_metadata_cannot_fail_otherwise_valid_stages(live_reaudit):
    _, summary = live_reaudit
    assert summary["real_model_calls"] == 0
    assert all(trial["returned"] and trial["parameters_generated"] for trial in summary["trials"])
    assert all(trial["stages"]["parameters"]["status"] == "success" for trial in summary["trials"])
    assert all(trial["stages"]["composition"]["status"] != "ValueError" for trial in summary["trials"])
    assert all(trial["stages"]["vision"]["sent_bytes_match_baseline"] for trial in summary["trials"])


def test_saved_live_aperture_crop_and_motion_claims_reconciled(live_reaudit):
    p05 = result(live_reaudit, "P05")
    assert p05["recommendation"]["aperture"] == "f/4"
    assert any("f/4" in reason for reason in p05["recommendation"]["reasons"])
    crop = next(item for item in p05["composition"]["proposals"] if item["action_type"] == "crop")
    assert "当前可见" in " ".join(crop["actions"])
    p10 = result(live_reaudit, "P10")
    assert p10["scene"]["subject_motion"] == "unknown"
    assert not any("慢门" in item or "快门" in item for item in p10["scene"]["recognition_evidence"])
    assert any(item["action_type"] == "crop" for item in p10["composition"]["proposals"])


def test_saved_live_unknown_iso_and_identity_constraints_remain_unverified(live_reaudit):
    p02 = result(live_reaudit, "P02")
    assert p02["recommendation"]["exposure_state"]["iso_control"] == "unknown"
    assert "无法校验" in p02["recommendation"]["shutter_speed"]
    assert p02["localization"]["queries"]["task_scope"]["selection_uncertainty"] == ["detector_multiple_candidates"]
    p06 = result(live_reaudit, "P06")
    scope = p06["localization"]["queries"]["task_scope"]
    assert "location_identity" in scope["selection_uncertainty"]
    assert "detector_multiple_candidates" in scope["selection_uncertainty"]
    assert not scope["intent_parse_uncertainties"]
    assert result(live_reaudit, "P09")["localization"]["selection"]["status"] == "ambiguous"
