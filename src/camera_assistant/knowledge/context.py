"""Shared exact-match context from target equipment and observed/user-provided facts.

Reference-photo EXIF is deliberately not an input. Unknown camera capabilities,
installed OS, shutter readout, drive mode and focus mode are never inferred.
"""

from __future__ import annotations

from typing import Any

from camera_assistant.models import CameraProfile, PhoneProfile, SceneAnalysis, UserRequest
from camera_assistant.services.phone_knowledge import normalized_model_name
from vision_lab_tool.detector_models import MethodResult

KNOWLEDGE_CONDITION_KEYS = frozenset(
    {
        "scene",
        "subject",
        "motion",
        "camera_profile_id",
        "camera_format",
        "camera_mount",
        "camera_lens_id",
        "device_type",
        "handheld",
        "tripod",
        "subject_confirmed",
        "phone_profile_id",
        "phone_capture_mode",
        "phone_lens_id",
        "phone_pro_controls_confirmed",
        "camera_model",
        "lens_model",
        "app",
        "os_major",
        "capture_mode",
        "lighting",
        "shutter_type",
        "drive_mode",
        "focus_mode",
        "region_scope",
    }
)

# Alias groups express the same exact model; adjacent generations/variants are excluded.
_MODEL_ALIASES = {
    "Canon EOS R6 Mark II": ("EOS R6 Mark II", "Canon R6 II", "canon_eos_r6_mark_ii"),
    "FUJIFILM X-T5": ("X-T5", "Fujifilm XT5", "fujifilm_x_t5"),
    "Apple iPhone 15": ("iPhone 15", "苹果15", "apple_iphone_15"),
    "Apple iPhone 16 Pro": ("iPhone 16 Pro", "苹果16 Pro", "apple_iphone_16_pro"),
    "Nikon Z6III": ("Nikon Z6 III", "Z6III", "Z6 III", "nikon_z6iii"),
    "Samsung Galaxy S24 Ultra": (
        "Galaxy S24 Ultra",
        "Samsung S24 Ultra",
        "S24 Ultra",
        "samsung_galaxy_s24_ultra",
    ),
    "Sony ILCE-7M4": (
        "Sony ILCE-7M4 (α7 IV)",
        "Sony α7 IV",
        "Sony A7 IV",
        "α7 IV",
        "A7 IV",
        "ILCE-7M4",
        "sony_a7iv",
    ),
    "Xiaomi 14": ("小米14", "xiaomi_14"),
}
_MODEL_NAMES = {
    normalized_model_name(alias): canonical
    for canonical, aliases in _MODEL_ALIASES.items()
    for alias in (canonical, *aliases)
}
_LENS_ALIASES = {
    "FUJINON XF18-55mmF2.8-4 R LM OIS": ("XF18-55mmF2.8-4 R LM OIS",),
    "NIKKOR Z 24-70mm f/4 S": ("Nikon NIKKOR Z 24-70mm f/4 S",),
    "Canon RF50mm F1.8 STM": ("RF50mm F1.8 STM", "Canon RF 50mm F1.8 STM"),
    "NIKKOR Z 50mm f/1.8 S": ("Nikon NIKKOR Z 50mm f/1.8 S",),
}
_LENS_NAMES = {
    normalized_model_name(alias): canonical
    for canonical, aliases in _LENS_ALIASES.items()
    for alias in (canonical, *aliases)
}
_APP_NAMES = {
    normalized_model_name("Apple 相机"): "Apple Camera",
    normalized_model_name("Apple Camera"): "Apple Camera",
    normalized_model_name("Samsung 相机"): "Samsung Camera",
    normalized_model_name("Samsung Camera"): "Samsung Camera",
    normalized_model_name("小米相机"): "Xiaomi Camera",
    normalized_model_name("Xiaomi 相机"): "Xiaomi Camera",
    normalized_model_name("Xiaomi Camera"): "Xiaomi Camera",
}


def build_knowledge_conditions(
    request: UserRequest,
    scene: SceneAnalysis,
    camera: CameraProfile | PhoneProfile,
    canonical_subject: str,
    localization: MethodResult | None = None,
) -> dict[str, Any]:
    """Preserve legacy context keys and add only reliable exact condition values.

    This is the still-photography workflow: cameras use ``still_photo``; phone
    ``auto`` means ``photo``. Other selected phone modes stay distinct. ``MF``
    maps to ``manual`` and ``efcs`` to ``electronic_front_curtain``. A generic
    electronic shutter never implies the card's ``electronic_rolling``.
    """
    motion = {"静止": "static", "缓慢": "slow", "快速": "fast"}.get(
        request.subject_motion, scene.subject_motion
    )
    conditions: dict[str, Any] = {
        "scene": scene.scene_type,
        "subject": canonical_subject,
        "motion": motion,
        "camera_profile_id": camera.profile_id,
        "device_type": camera.device_type,
        "handheld": request.handheld,
        "tripod": request.tripod,
        "subject_confirmed": bool(localization and localization.selection.status == "selected"),
    }
    is_phone = isinstance(camera, PhoneProfile)
    if is_phone:
        if camera.capability_level == "catalog" and camera.region_scope == "中国大陆":
            conditions["region_scope"] = camera.region_scope
        conditions.update(
            {
                "phone_profile_id": camera.profile_id,
                "phone_capture_mode": request.phone_capture_mode,
                "phone_lens_id": request.phone_lens_id,
                "phone_pro_controls_confirmed": request.phone_pro_controls_confirmed,
                "capture_mode": "photo"
                if request.phone_capture_mode == "auto"
                else request.phone_capture_mode,
            }
        )
    else:
        conditions.update({
            "camera_format": camera.sensor_format, "capture_mode": "still_photo",
            "camera_mount": (request.declared_camera_mount
                             if request.camera_lens_reference_id and request.declared_camera_mount
                             else camera.mount), "camera_lens_id": request.camera_lens_id,
        })

    target_model = (request.target_model_name or request.device_model_name or "").strip()
    # 已选具体档案与参数能力必须指向同一设备；自填型号只补充通用档案。
    if not camera.profile_id.startswith("generic_"):
        target_model = camera.display_name
    if target_model:
        conditions["camera_model"] = _MODEL_NAMES.get(
            normalized_model_name(target_model), target_model
        )

    target_lens = (getattr(request, "target_lens_name", None) or "").strip()
    if target_lens:
        conditions["lens_model"] = _LENS_NAMES.get(normalized_model_name(target_lens), target_lens)

    app = (getattr(request, "camera_app", None) or "").strip()
    profile_model = _MODEL_NAMES.get(
        normalized_model_name(camera.display_name), camera.display_name
    )
    if (
        is_phone
        and not camera.profile_id.startswith("generic_")
        and conditions.get("camera_model") == profile_model
        and (not app or normalized_model_name(app) in {"nativecamera", "原生相机"})
    ):
        app = camera.native_app
    if app:
        conditions["app"] = _APP_NAMES.get(normalized_model_name(app), app)

    os_major = getattr(request, "os_major", None)
    if os_major is not None:
        conditions["os_major"] = (
            f"iOS {os_major}"
            if str(conditions.get("camera_model", "")).startswith("Apple iPhone ")
            else os_major
        )

    shutter = getattr(request, "shutter_type", None)
    if shutter:
        conditions["shutter_type"] = {"efcs": "electronic_front_curtain"}.get(shutter, shutter)
    drive = getattr(request, "drive_mode", None)
    if drive:
        conditions["drive_mode"] = drive
    focus = getattr(request, "focus_mode", None)
    if focus:
        conditions["focus_mode"] = {"MF": "manual", "DMF": "direct_manual"}.get(focus, focus)
    confirmed_lighting = getattr(request, "lighting_type", None)
    lighting = (confirmed_lighting or scene.lighting).strip()
    # A single-photo model observation cannot establish light-source flicker.
    if confirmed_lighting is None and lighting == "flickering_artificial":
        lighting = ""
    if lighting:
        conditions["lighting"] = lighting
    return conditions
