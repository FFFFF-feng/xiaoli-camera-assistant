"""App interactions must never leave the explicit inference action boundary."""
import json

import pytest
from streamlit.testing.v1 import AppTest

from vision_lab_tool.detector_storage import DetectorStore, export_csv, export_json

PAGE = """
import os
from pathlib import Path
from vision_lab_tool.models import ModelConfig
from vision_lab_tool.ui_detectors import render_detector_page
render_detector_page(Path(os.environ['DETECTOR_UI_TEST_ROOT']), [
    ModelConfig(config_id='glm', name='GLM-4.6V', provider='智谱', protocol='chat',
                model_id='glm-4.6v', base_url='https://example.invalid/v1',
                key_env='ZHIPU_API_KEY')
], {}, ['test-private-secret'])
"""


def by_label(elements, label):
    return next(element for element in elements if element.label == label)


def active_run(app):
    run = app.session_state["detector_active_run"]
    assert run is not None, [item.value for item in app.error]
    return run


def app_for(monkeypatch, tmp_path):
    monkeypatch.setenv("DETECTOR_UI_TEST_ROOT", str(tmp_path))
    return AppTest.from_string(PAGE, default_timeout=30)


def prepare_simulation(app, mode="纯检测", case="valid"):
    app.run()
    by_label(app.checkbox, "模拟验证（不联网、不加载权重）").set_value(True).run()
    by_label(app.radio, "检测实验入口").set_value(mode).run()
    by_label(app.selectbox, "模拟夹具").set_value(case).run()
    by_label(app.button, "使用检测内置示例图").click().run()
    return app


def test_detector_page_starts_without_environment_or_key(monkeypatch, tmp_path):
    from vision_lab_tool import detector_runner

    calls = []
    monkeypatch.setattr(detector_runner, "invoke_localization", lambda *a, **k: calls.append(1))
    app = app_for(monkeypatch, tmp_path).run()
    assert not app.exception
    assert by_label(app.button, "运行检测").disabled
    assert app.file_uploader[0].label == "上传检测照片"
    assert calls == []


def test_single_detector_no_vlm_repeated_interactions_frozen_params(monkeypatch, tmp_path):
    from vision_lab_tool import detector_runner

    vlm_calls, detector_calls = [], []
    detect_original = detector_runner.detect_mock

    def unexpected_vlm(*args, **kwargs):
        vlm_calls.append(1)
        raise AssertionError("纯检测不得调用视觉模型")

    def count_detect(*args, **kwargs):
        detector_calls.append(1)
        return detect_original(*args, **kwargs)

    monkeypatch.setattr(detector_runner, "invoke_localization", unexpected_vlm)
    monkeypatch.setattr(detector_runner, "detect_mock", count_detect)
    app = prepare_simulation(app_for(monkeypatch, tmp_path))
    by_label(app.multiselect, "检测器（可只选一个）").set_value(["yolo26"]).run()
    by_label(app.button, "运行检测").click().run()
    assert not app.exception
    run = active_run(app)
    assert run.vlm is None and len(run.results) == 1
    assert detector_calls == [1] and vlm_calls == []
    original_version, original_task = run.experiment_version, run.task_prompt
    by_label(app.text_input, "检测实验版本").set_value("later-version").run()
    by_label(app.text_area, "共同定位任务").set_value("later-task").run()
    by_label(app.checkbox, "已完成人工评测 · YOLO26n").set_value(True).run()
    human_id = run.results[0].candidates[0].object_id
    by_label(app.multiselect, "人工辅助主体 ID · YOLO26n").set_value([human_id]).run()
    by_label(app.selectbox, "人工辅助主体是否正确 · YOLO26n").set_value("正确").run()
    by_label(app.text_area, "人工评测备注 · YOLO26n").set_value("test-private-secret").run()
    by_label(app.checkbox, "主动保存检测照片副本（本地去 EXIF）").set_value(True).run()
    by_label(app.button, "保存检测记录与评测").click().run()
    by_label(app.button, "重新打开检测历史").click().run()
    by_label(app.multiselect, "筛选：真实 / 模拟").set_value(["模拟"]).run()
    app.run()
    assert not app.exception
    restored = app.session_state["detector_active_run"]
    assert restored.experiment_version == original_version and restored.task_prompt == original_task
    assert restored.results[0].selection.selected_ids == []
    assert restored.evaluations[restored.results[0].result_id].human_selected_ids == [human_id]
    assert detector_calls == [1] and vlm_calls == []
    exported = export_json([restored], ["test-private-secret"])
    exported_csv = export_csv([restored], ["test-private-secret"])
    assert b"test-private-secret" not in exported + exported_csv
    assert len(DetectorStore(tmp_path).list_runs()) == 2
    assert DetectorStore(tmp_path).load_sample(restored).size == (800, 500)
    assert len(app.get("download_button")) == 2


def test_localization_shared_once_and_history_zero_extra_calls(monkeypatch, tmp_path):
    from vision_lab_tool import detector_runner

    vlm_calls, detector_calls = [], []
    invoke_original, detect_original = detector_runner.invoke_localization, detector_runner.detect_mock

    def count_vlm(*args, **kwargs):
        vlm_calls.append(1)
        return invoke_original(*args, **kwargs)

    def count_detect(*args, **kwargs):
        detector_calls.append(1)
        return detect_original(*args, **kwargs)

    monkeypatch.setattr(detector_runner, "invoke_localization", count_vlm)
    monkeypatch.setattr(detector_runner, "detect_mock", count_detect)
    app = prepare_simulation(app_for(monkeypatch, tmp_path), mode="定位对照")
    assert by_label(app.selectbox, "联合定位语义基线").value == "glm"
    assert not any("手工英文查询" in item.label for item in app.text_area)
    by_label(app.button, "运行对照").click().run()
    assert not app.exception
    run = active_run(app)
    assert [result.method for result in run.results] == ["A", "B1", "B2"]
    assert len(vlm_calls) == 1 and len(detector_calls) == 2
    by_label(app.checkbox, "已完成人工评测 · A").set_value(True).run()
    by_label(app.button, "保存检测记录与评测").click().run()
    by_label(app.button, "重新打开检测历史").click().run()
    identity = "GLM-4.6V · glm-4.6v"
    assert identity in by_label(app.multiselect, "筛选：模型 / 检测器").options
    by_label(app.multiselect, "筛选：模型 / 检测器").set_value([identity]).run()
    by_label(app.multiselect, "筛选：阶段").set_value(["json"]).run()
    by_label(app.multiselect, "筛选：方法").set_value(["B1"]).run()
    app.run()
    assert not app.exception and len(vlm_calls) == 1 and len(detector_calls) == 2
    by_label(app.multiselect, "筛选：方法").set_value([]).run()
    by_label(app.multiselect, "筛选：阶段").set_value([]).run()
    by_label(app.button, "运行对照").click().run()
    second = app.session_state["detector_active_run"]
    assert second.attempt_id != run.attempt_id and second.run_id != run.run_id
    assert second.vlm.cache_hit and all(result.detection.cache_hit for result in second.results[1:])
    assert len(vlm_calls) == 1 and len(detector_calls) == 2


def test_prompt_version_controls_only_next_explicit_run_and_history_is_frozen(monkeypatch, tmp_path):
    from vision_lab_tool import detector_runner

    vlm_calls, detector_calls = [], []
    original_invoke, original_detect = detector_runner.invoke_localization, detector_runner.detect_mock

    def count_vlm(*args, **kwargs):
        vlm_calls.append(kwargs["prompt_version"])
        return original_invoke(*args, **kwargs)

    def count_detect(*args, **kwargs):
        detector_calls.append(1)
        return original_detect(*args, **kwargs)

    monkeypatch.setattr(detector_runner, "invoke_localization", count_vlm)
    monkeypatch.setattr(detector_runner, "detect_mock", count_detect)
    app = prepare_simulation(app_for(monkeypatch, tmp_path), mode="定位对照")
    options = by_label(app.selectbox, "定位提示词版本")
    assert options.value == detector_runner.CANDIDATE_PROMPT_VERSION
    assert vlm_calls == [] and detector_calls == []
    options.set_value(detector_runner.BASELINE_PROMPT_VERSION).run()
    assert vlm_calls == [] and detector_calls == []
    by_label(app.button, "运行对照").click().run()
    baseline = active_run(app).model_copy(deep=True)
    assert vlm_calls == [detector_runner.BASELINE_PROMPT_VERSION] and len(detector_calls) == 2
    by_label(app.selectbox, "定位提示词版本").set_value(
        detector_runner.CANDIDATE_PROMPT_VERSION).run()
    assert active_run(app).run_id == baseline.run_id
    assert active_run(app).provenance == baseline.provenance
    assert len(vlm_calls) == 1 and len(detector_calls) == 2
    assert any(baseline.provenance["localization_prompt_sha256"] in item.value for item in app.caption)
    assert any(item.value == baseline.provenance["localization_prompt"] for item in app.code)
    by_label(app.button, "运行对照").click().run()
    first_candidate = active_run(app).model_copy(deep=True)
    assert first_candidate.run_id != baseline.run_id and not first_candidate.vlm.cache_hit
    assert first_candidate.provenance["localization_prompt_version"] == (
        detector_runner.CANDIDATE_PROMPT_VERSION)
    assert len(vlm_calls) == 2 and len(detector_calls) == 4
    by_label(app.selectbox, "定位提示词版本").set_value(detector_runner.SCOPE_PROMPT_VERSION).run()
    assert active_run(app).run_id == first_candidate.run_id
    assert active_run(app).provenance == first_candidate.provenance
    assert len(vlm_calls) == 2
    by_label(app.button, "运行对照").click().run()
    scoped = active_run(app)
    assert not scoped.vlm.cache_hit
    assert scoped.provenance["localization_prompt_version"] == detector_runner.SCOPE_PROMPT_VERSION
    assert vlm_calls == [detector_runner.BASELINE_PROMPT_VERSION,
                         detector_runner.CANDIDATE_PROMPT_VERSION, detector_runner.SCOPE_PROMPT_VERSION]
    assert len(detector_calls) == 6
    by_label(app.selectbox, "选择检测历史").set_value(baseline.run_id).run()
    by_label(app.button, "重新打开检测历史").click().run()
    reopened = active_run(app)
    assert not app.exception and reopened.run_id == baseline.run_id
    assert reopened.provenance == baseline.provenance
    assert len(vlm_calls) == 3 and len(detector_calls) == 6
    assert any(baseline.provenance["localization_prompt_sha256"] in item.value for item in app.caption)
    assert any(item.value == baseline.provenance["localization_prompt"] for item in app.code)


@pytest.mark.parametrize("case", [
    "empty", "duplicate_id", "invalid_box", "ambiguous", "overlap", "unsupported",
    "vlm_network", "vlm_json", "vlm_semantic", "vlm_invalid_box",
])
def test_failure_and_ambiguity_fixture_ui_keeps_all_methods(monkeypatch, tmp_path, case):
    app = prepare_simulation(app_for(monkeypatch, tmp_path), mode="定位对照", case=case)
    by_label(app.button, "运行对照").click().run()
    assert not app.exception
    run = active_run(app)
    assert [result.method for result in run.results] == ["A", "B1", "B2"]
    assert run.simulated and all(not result.real for result in run.results)
    by_label(app.button, "保存检测记录与评测").click().run()
    assert not app.exception
    assert len(DetectorStore(tmp_path).list_runs()) == 2


def test_error_ids_and_invalid_gt_do_not_crash_ui(monkeypatch, tmp_path):
    app = prepare_simulation(app_for(monkeypatch, tmp_path))
    by_label(app.multiselect, "检测器（可只选一个）").set_value(["yolo26"]).run()
    by_label(app.button, "运行检测").click().run()
    assert not app.exception
    run = active_run(app)
    # This is the public data_editor state format; invalid coordinates must remain draft.
    editor_key = f"det-ref:{run.run_id}:objects"
    app.session_state[editor_key] = {
        "edited_rows": {}, "deleted_rows": [], "added_rows": [
            {"gt_id": "gt-invalid", "label": "person", "x_min": .9, "y_min": .1,
             "x_max": .2, "y_max": .7}
        ],
    }
    app.run()
    assert not app.exception
    assert app.session_state["detector_active_run"].reference.objects == []
    assert any("人工标注尚未合法" in item.value for item in app.error)
    by_label(app.button, "保存检测记录与评测").click().run()
    assert not app.exception


def test_confirmed_reference_pairing_and_multiple_error_entries(monkeypatch, tmp_path):
    from vision_lab_tool.detector_evaluation import result_metrics

    app = prepare_simulation(app_for(monkeypatch, tmp_path))
    by_label(app.multiselect, "检测器（可只选一个）").set_value(["yolo26"]).run()
    by_label(app.button, "运行检测").click().run()
    run = active_run(app)
    obj = run.results[0].candidates[0]
    by_label(app.text_area, "参考框 JSON").set_value(json.dumps({
        "complete": False, "main_subject_judgeable": True, "objects": [{
            "gt_id": "gt-1", "label": "person", "bbox": obj.bbox,
            "confirmed": False, "user_main_subject": True, "annotation_source": "ai",
        }],
    })).run()
    by_label(app.button, "应用参考 JSON").click().run()
    by_label(app.multiselect, "本次明确确认的参考 ID").set_value(["gt-1"]).run()
    by_label(app.text_area, "人工确认原文").set_value("此人物实例存在，边界完整").run()
    by_label(app.text_input, "参考修订理由").set_value("复核AI预标注").run()
    by_label(app.button, "确认所选对象与边界").click().run()
    by_label(app.checkbox, "人工参考完整且逐框已确认").set_value(True).run()
    by_label(app.checkbox, "已完成人工评测 · YOLO26n").set_value(True).run()
    by_label(app.selectbox, f"YOLO26n · {obj.object_id} (person) 对应参考框").set_value("gt-1").run()
    by_label(app.multiselect, "人工辅助主体 ID · YOLO26n").set_value([obj.object_id]).run()
    by_label(app.selectbox, "人工辅助主体是否正确 · YOLO26n").set_value("正确").run()
    by_label(app.text_area, "配对确认原文 · YOLO26n").set_value("此预测与gt-1为同一实例").run()
    by_label(app.text_input, "配对修订理由 · YOLO26n").set_value("人工核对对应关系").run()
    by_label(app.button, "确认当前配对与评测范围 · YOLO26n").click().run()
    result = run.results[0]
    by_label(app.text_area, "错误条目 JSON · YOLO26n").set_value(json.dumps([
        {"tag": "检测误检", "evidence": "first", "confirmed": True},
        {"tag": "检测误检", "evidence": "second", "confirmed": False},
    ])).run()
    by_label(app.button, "应用错误 JSON · YOLO26n").click().run()
    assert not app.exception
    active = app.session_state["detector_active_run"]
    assert len(active.reference.objects) == 1 and active.reference.complete
    errors = active.evaluations[result.result_id].errors
    assert len(errors) == 2 and errors[0].error_id != errors[1].error_id
    error_ids = [error.error_id for error in errors]
    by_label(app.text_area, "检测人工参考备注").set_value("updated notes").run()
    active = app.session_state["detector_active_run"]
    assert len(active.reference.objects) == 1
    assert [error.error_id for error in active.evaluations[result.result_id].errors] == error_ids
    metrics = result_metrics(active, active.results[0])
    assert metrics["tp"] == 1 and metrics["fn"] == 0 and metrics["mean_iou"] == 1
    assert metrics["subject_correct_auto"] is False and metrics["subject_correct_human"] is True
    by_label(app.button, "保存检测记录与评测").click().run()
    by_label(app.button, "重新打开检测历史").click().run()
    restored = app.session_state["detector_active_run"]
    assert not app.exception and restored.reference.complete
    assert len(restored.evaluations[result.result_id].errors) == 2


def test_ai_json_partial_confirmation_save_history_and_export_never_infer(monkeypatch, tmp_path):
    from vision_lab_tool import ui_detectors
    from vision_lab_tool.detector_evaluation import result_metrics

    app = prepare_simulation(app_for(monkeypatch, tmp_path))
    by_label(app.multiselect, "检测器（可只选一个）").set_value(["yolo26"]).run()
    by_label(app.button, "运行检测").click().run()
    original = active_run(app).model_copy(deep=True)
    store = DetectorStore(tmp_path)
    original_bytes = (store.root / "runs" / f"{original.run_id}.json").read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("编辑、保存、重开、版本切换及导出不得调用推理")

    monkeypatch.setattr(ui_detectors, "run_experiment", forbidden)
    forged = {"complete": True, "objects": [
        {"gt_id": gid, "label": "person", "bbox": [.1, .1, .8, .9],
         "annotation_source": "ai", "confirmed": True}
        for gid in ["one", "two"]
    ]}
    by_label(app.text_area, "参考框 JSON").set_value(json.dumps(forged)).run()
    by_label(app.button, "应用参考 JSON").click().run()
    assert not active_run(app).reference.complete
    assert not any(obj.confirmed for obj in active_run(app).reference.objects)
    by_label(app.multiselect, "本次明确确认的参考 ID").set_value(["one"]).run()
    by_label(app.text_area, "人工确认原文").set_value("仅one人物和边界确认，two待定").run()
    by_label(app.text_input, "参考修订理由").set_value("第一项人工复核").run()
    by_label(app.button, "确认所选对象与边界").click().run()
    assert [obj.confirmed for obj in active_run(app).reference.objects] == [True, False]
    by_label(app.checkbox, "人工参考完整且逐框已确认").set_value(True).run()
    assert not active_run(app).reference.complete
    assert result_metrics(active_run(app), active_run(app).results[0])["tp"] is None
    by_label(app.button, "保存检测记录与评测").click().run()
    derived = active_run(app)
    assert derived.run_id != original.run_id
    assert (store.root / "runs" / f"{original.run_id}.json").read_bytes() == original_bytes
    by_label(app.selectbox, "选择检测历史").set_value(original.run_id).run()
    by_label(app.button, "重新打开检测历史").click().run()
    assert active_run(app).reference.objects == []
    by_label(app.selectbox, "选择检测历史").set_value(derived.run_id).run()
    by_label(app.button, "重新打开检测历史").click().run()
    assert [obj.confirmed for obj in active_run(app).reference.objects] == [True, False]
    assert json.loads(export_json([active_run(app)]))[0]["reference"]["complete"] is False
    assert export_csv([active_run(app)])
    assert not app.exception


def test_default_task_contains_frozen_person_query(monkeypatch, tmp_path):
    app = prepare_simulation(app_for(monkeypatch, tmp_path))
    by_label(app.button, "运行检测").click().run()
    assert not app.exception
    run = active_run(app)
    grounding = next(result for result in run.results if result.detector == "grounding_dino")
    assert "person" in grounding.queries["from_task"]


def test_background_cancellation_preserves_stage_snapshot(monkeypatch, tmp_path):
    import threading

    from vision_lab_tool import ui_detectors

    original = ui_detectors.run_experiment
    calls, stops = [], []
    stages_persisted = threading.Event()

    def background_fixture(image, **kwargs):
        calls.append(1)
        cancel = kwargs.pop("cancel_event")
        kwargs["simulated"] = True
        run = original(image, **kwargs)
        stages_persisted.set()
        cancel.wait(10)
        run.stages["run"] = "cancelled"
        run.results[0].status = "cancelled"
        return run

    monkeypatch.setattr(ui_detectors, "run_experiment", background_fixture)
    monkeypatch.setattr(ui_detectors, "stop_worker", lambda: stops.append(1))
    app = app_for(monkeypatch, tmp_path).run()
    by_label(app.multiselect, "检测器（可只选一个）").set_value(["yolo26"]).run()
    by_label(app.button, "使用检测内置示例图").click().run()
    by_label(app.button, "运行检测").click().run()
    assert not app.exception and calls == [1]
    job = app.session_state["detector_job"]
    assert job.thread is not None
    assert stages_persisted.wait(5)
    assert len(DetectorStore(tmp_path).list_runs()) == 1
    app.run()
    assert calls == [1]
    by_label(app.button, "取消当前检测任务").click().run()
    # The fixture returns before the job saves its result and marks itself done.
    # Wait for the actual background task before asking the UI to consume it.
    job.thread.join(timeout=5)
    assert not job.thread.is_alive() and job.done
    app.run()
    assert not app.exception and calls == [1] and stops == [1]
    assert app.session_state["detector_active_run"].stages["run"] == "cancelled"


def test_stage_storage_failure_keeps_results_for_download(monkeypatch, tmp_path):
    def inaccessible_store(*args, **kwargs):
        raise OSError("simulated locked storage")

    monkeypatch.setattr(DetectorStore, "save_run", inaccessible_store)
    app = prepare_simulation(app_for(monkeypatch, tmp_path), mode="定位对照")
    by_label(app.button, "运行对照").click().run()
    run = active_run(app)
    assert not app.exception and [result.method for result in run.results] == ["A", "B1", "B2"]
    assert any("阶段记录写盘失败" in item.value for item in app.warning)
    assert len(app.get("download_button")) == 2


def test_history_exports_are_generated_only_on_download_and_never_infer(monkeypatch, tmp_path):
    import streamlit as st
    from streamlit.delta_generator import DeltaGenerator
    from test_detector_evaluation import experiment

    from vision_lab_tool import ui_detectors

    if tuple(map(int, st.__version__.split(".")[:2])) < (1, 65):
        pytest.skip("Legacy Streamlit uses its original eager bytes download contract")

    DetectorStore(tmp_path).save_run(experiment())
    calls, downloads = [], {}
    original = DeltaGenerator.download_button

    def capture(self, label, data, *args, **kwargs):
        downloads[label] = data
        return original(self, label, data, *args, **kwargs)

    def infer(*args, **kwargs):
        pytest.fail("History/export reached inference")

    monkeypatch.setattr(DeltaGenerator, "download_button", capture)
    monkeypatch.setattr(ui_detectors, "run_experiment", infer)
    monkeypatch.setattr(ui_detectors, "export_json", lambda *a: calls.append("json") or b"[]")
    monkeypatch.setattr(ui_detectors, "export_csv", lambda *a: calls.append("csv") or b"header")
    app = app_for(monkeypatch, tmp_path).run()
    assert not app.exception
    assert calls == []
    assert callable(downloads["下载检测 JSON"]) and callable(downloads["下载检测 CSV"])
    assert downloads["下载检测 JSON"]() == b"[]"
    assert downloads["下载检测 CSV"]() == b"header"
    assert calls == ["json", "csv"]
