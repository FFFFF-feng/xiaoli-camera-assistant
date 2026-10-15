import json

import pytest
from test_vision_lab_core import image_bytes

from vision_lab_tool.evaluation import aggregate, estimate_cost, result_metrics
from vision_lab_tool.images import prepare_image
from vision_lab_tool.models import Evaluation, ModelConfig, Price, Reference, Usage, VisibleObject
from vision_lab_tool.runner import run_comparison
from vision_lab_tool.storage import Store, export_csv, export_json


def mock_configs():
    return [
        ModelConfig(name="模拟正常", provider="模拟", protocol="mock"),
        ModelConfig(name="模拟失败", provider="模拟", protocol="mock", mock_case="failure"),
    ]


def run():
    return run_comparison(
        mock_configs(),
        prepare_image(image_bytes()),
        "recognition",
        "template",
        {},
        "v1",
        "开发",
        "p1",
    )


def test_one_failure_retains_other_result():
    record = run()
    assert [r.status for r in record.results] == ["ok", "http_error"]
    assert len({r.result_id for r in record.results}) == 2
    assert record.context["include_exif"] is False


def test_missing_reference_does_not_become_accuracy():
    record = run()
    metrics = result_metrics(record, record.results[0])
    assert metrics["scene_match"] is None and metrics["ious"] == []
    assert aggregate([record]) == []  # default quality summary excludes mock fixtures
    summaries = aggregate([record], include_mock=True)
    assert summaries[0]["scene_evaluated"] == 0
    assert summaries[0]["scene_missing"] == 1
    assert summaries[0]["human_evaluated"] == 0


def test_explicit_box_pairing_and_scene_denominator():
    record = run()
    result = record.results[0]
    record.reference = Reference(
        scene_labels=["模拟测试场景"],
        scene_annotated=True,
        objects=[
            VisibleObject(
                object_id="ref1", label="主体", bbox=[0.2, 0.15, 0.7, 0.85], confidence=None
            )
        ],
    )
    assert result_metrics(record, result)["ious"] == []
    record.evaluations[result.result_id] = Evaluation(reviewed=True, box_matches={"obj1": "ref1"})
    metrics = result_metrics(record, result)
    assert metrics["ious"] == [1] and metrics["scene_match"] is True
    summary = aggregate([record], include_mock=True)[0]
    assert summary["samples"] == 1 and summary["human_evaluated"] == 1
    assert summary["scene_evaluated"] == 1 and summary["scene_missing"] == 0


def test_reasoning_not_double_billed_and_currency():
    price = Price(
        input_per_million=1,
        output_per_million=2,
        currency="CNY",
        cache_per_million=0.5,
        source_url="https://price.example",
        checked_on="2026-10-11",
    )
    usage = Usage(input_tokens=1000, output_tokens=200, cached_tokens=100, reasoning_tokens=100)
    assert estimate_cost(usage, price)["amount"] == pytest.approx(0.00135)
    usage.output_includes_reasoning = False
    assert estimate_cost(usage, price)["amount"] == pytest.approx(0.00155)
    assert estimate_cost(Usage(), price) is None
    assert estimate_cost(usage, Price()) is None
    assert (
        estimate_cost(
            Usage(input_tokens=10, output_tokens=20, output_includes_reasoning=False), price
        )
        is None
    )


def test_store_history_exports_no_images_by_default(tmp_path):
    record = run()
    record.reference.notes = "继续评测"
    record.evaluations[record.results[0].result_id] = Evaluation(reviewed=True)
    store = Store(tmp_path)
    store.save_run(record)
    reopened = store.load_run(record.run_id)
    assert reopened.reference.notes == "继续评测"
    assert reopened.evaluations[record.results[0].result_id].reviewed
    assert len(store.list_runs()) == 1
    assert not list(tmp_path.rglob("*.jpg")) and not list(tmp_path.rglob("*.png"))
    assert "image" in json.loads(export_json([reopened]))[0]
    csv = export_csv([reopened]).decode("utf-8-sig")
    assert "model_id" in csv and "image_sha256" in csv and "experiment_version" in csv
    with pytest.raises(ValueError):
        store.load_run("../outside")


def test_export_scrubs_echoes_and_formula_injection():
    record = run()
    record.reference.notes = '=HYPERLINK("evil")'
    record.results[0].raw_answer = "sk-abcdefghijklmnop data:image/jpeg;base64,AAAA"
    serialized = export_json([record]).decode()
    assert "sk-abcdefghijklmnop" not in serialized and "AAAA" not in serialized
    assert "'=HYPERLINK" in export_csv([record]).decode("utf-8-sig")


def test_save_configuration_contains_key_source_only(tmp_path):
    store = Store(tmp_path)
    config = ModelConfig(name="test", provider="test", protocol="chat", key_env="MY_API_KEY")
    store.save_configs([config])
    assert store.load_configs()[0].key_env == "MY_API_KEY"
    assert "api_key" not in (tmp_path / "configs.json").read_text(encoding="utf-8")


def test_opt_in_sample_save(tmp_path):
    store = Store(tmp_path)
    record = run()
    prepared = prepare_image(image_bytes(orientation=6))
    store.save_sample(record, prepared)
    store.save_run(record)
    image = store.load_sample(record)
    assert image.size == prepared.corrected.size
    assert not image.getexif()


def test_different_request_settings_do_not_merge_quality_results():
    first = run()
    second = first.model_copy(deep=True)
    second.run_id = "a" * 32
    second.results[0].config.base_url = "https://other.example/v1"
    second.results[0].config.detail = "high"
    summaries = [
        s
        for s in aggregate([first, second], include_mock=True)
        if s["config_id"] == first.results[0].config.config_id
    ]
    assert len(summaries) == 2
