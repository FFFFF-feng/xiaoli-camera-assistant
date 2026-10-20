import pytest
from test_device_reference_catalog import publish
from test_device_selection import photo, pipeline

from camera_assistant.models import UserRequest
from camera_assistant.services.device_optics import lens_specifications, phone_lenses
from camera_assistant.services.lens_knowledge import EquipmentSelectionError


def test_phone_text_main_ultrawide_macro_and_apertures():
    lenses = phone_lenses({"rear": "2亿像素广角摄像头(f/1.9光圈，OIS)；5000万像素长焦摄像头(f/2.4)；1200万像素超广角微距摄像头(f/2.2)"})
    assert [(x.name, x.aperture) for x in lenses] == [("主摄", 1.9), ("长焦", 2.4), ("超广角", 2.2)]
    assert all(x.modes == ["auto"] and x.aperture_control == "unknown" for x in lenses)


def test_phone_explicit_parenthetical_aperture_assignment():
    lenses = phone_lenses({"rear": "5000万主摄+5000万潜望长焦+5000万超广角；光圈按厂商顺序：f/1.88（后置主摄），f/2.65（后置潜望），f/2.05（后置超广角）"})
    assert [(x.name, x.aperture) for x in lenses] == [("主摄", 1.88), ("长焦", 2.65), ("超广角", 2.05)]


def test_phone_plus_can_join_fields_not_only_cameras():
    lenses = phone_lenses({"rear": "主摄/广角：5000万像素+ƒ/1.88+等效焦距24MM；超广角/微距：1600万像素+ƒ/2.4+等效焦距16MM；景深500万像素+ƒ/2.4"})
    assert [(x.name, x.aperture, x.equivalent_focal_length_mm) for x in lenses] == [("主摄", 1.88, 24), ("超广角", 2.4, 16)]


def test_phone_no_fabricated_lenses_from_dual_camera_or_crop_ratio():
    assert len(phone_lenses({"rear": "5000万像素+200万像素双摄，30倍数字变焦"})) == 1
    lenses = phone_lenses({"cameras": {"rear_entries": [{"role": "主摄", "aperture_f_number": 1.6},
        {"role": "2倍裁切长焦", "aperture_f_number": 1.6}, {"role": "前置"}]}})
    assert len(lenses) == 1 and lenses[0].aperture == 1.6
    assert lenses[0].equivalent_focal_length_mm is None


def test_marketing_three_main_cameras_are_not_three_identical_main_entries():
    lenses = phone_lenses({"rear": "5000万超清三主摄；5000万广角主摄；5000万人像主摄f/1.9等效50mm；5000万超广角主摄f/2.2"})
    assert [x.name for x in lenses] == ["主摄", "人像镜头", "超广角"]
    assert lenses[0].aperture is None


def test_lens_model_explicit_specifications_not_calibration_samples():
    result = lens_specifications({"model": "Nikon AF-S 18-55mm f/3.5-5.6G VR",
                                  "source_metadata": {"cropfactor": [{"text": "1.5"}]}})
    assert (result["focal_min_mm"], result["focal_max_mm"]) == (18, 55)
    assert (result["max_aperture_wide"], result["max_aperture_tele"]) == (3.5, 5.6)
    assert result["sensor_formats"] == []  # 校正cropfactor不冒充成像圈。
    assert not lens_specifications({"model": "Unknown", "calibration_sample_counts": {"focal": 18}})["parameter_linkage"]


def structured():
    return {"entity_type": "lens", "model": "fixture", "brand": "Fixture", "mounts": ["Sony E"],
        "source_product": {"lens": {"coverage": {"format": "aps-c"},
            "focalLength": {"kind": "zoom", "rangeMm": {"minimum": 18, "maximum": 55}},
            "aperture": {"fNumber": {"maximumAperture": [
                {"value": 3.5, "conditions": {"focalLength": {"kind": "point", "millimeters": 18}}},
                {"value": 5.6, "conditions": {"focalLength": {"kind": "point", "millimeters": 55}}}]}}}}}


def test_structured_zoom_endpoints_and_coverage():
    spec = lens_specifications(structured())
    assert spec["sensor_formats"] == ["APS-C"]
    assert spec["max_aperture_wide"] == 3.5 and spec["max_aperture_tele"] == 5.6


def test_pipeline_reference_lens_parameters_are_actually_linked(tmp_path):
    app = pipeline(tmp_path)
    publish(tmp_path / "unused.db", "source-specs", structured())
    app = type(app)(app.settings)
    reference = app.lens_references[0]
    request = UserRequest(intent="拍摄静物", camera_profile_id="sony_a6400",
        camera_lens_reference_id=reference["reference_id"], focal_length_mm=500, max_aperture=1.2)
    result = app.run(photo(), request)
    settings = result.equipment_settings
    assert settings.focal_length_mm == 55
    assert settings.max_aperture == 5.6 and settings.equivalent_focal_length_mm == 82.5
    assert settings.reference_lens["reference_id"] == reference["reference_id"]
    with pytest.raises(EquipmentSelectionError):
        app.run(photo(), request.model_copy(update={"camera_profile_id": "sony_a7_iii"}))
