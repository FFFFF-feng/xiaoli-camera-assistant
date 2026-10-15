from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from camera_assistant.composition_models import CompositionAdvice
from vision_lab_tool.detector_models import MethodResult, SemanticObject

MotionLevel = Literal["静止", "缓慢", "快速", "不确定"]
CameraFormat = Literal["全画幅", "APS-C", "M4/3", "不清楚"]
PhoneCaptureMode = Literal["auto", "portrait", "night", "pro"]


class UserRequest(BaseModel):
    intent: str = Field(min_length=2, max_length=500)
    subject_motion: MotionLevel = "不确定"
    handheld: bool = True
    tripod: bool = False
    camera_format: CameraFormat = "不清楚"
    camera_profile_id: str = "generic_unknown"
    camera_lens_id: str = Field(default="", max_length=100)
    focal_length_mm: int | None = Field(default=None, ge=8, le=1200)
    max_aperture: float | None = Field(default=None, ge=0.7, le=32)
    device_type: Literal["camera", "phone"] = "camera"
    device_model_name: str = Field(default="", max_length=120)
    phone_profile_id: str = "generic_phone"
    phone_capture_mode: PhoneCaptureMode = "auto"
    phone_lens_id: str = "main"
    phone_pro_controls_confirmed: bool = False
    target_model_name: str | None = Field(default=None, max_length=120)
    target_lens_name: str | None = Field(default=None, max_length=160)
    camera_app: str | None = Field(default=None, max_length=80)
    os_major: int | None = Field(default=None, ge=1, le=100, strict=True)
    shutter_type: Literal["mechanical", "electronic", "efcs"] | None = None
    drive_mode: Literal["single", "continuous"] | None = None
    focus_mode: Literal["AF-S", "AF-C", "MF"] | None = None
    lighting_type: Literal["natural", "continuous_artificial", "flickering_artificial", "mixed"] | None = None

    @field_validator("target_model_name", "target_lens_name", "camera_app")
    @classmethod
    def optional_label(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("device_model_name")
    @classmethod
    def validate_device_model_name(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("设备型号不能包含换行或控制字符")
        return value.strip()


class ExifInfo(BaseModel):
    camera_make: str | None = None
    camera_model: str | None = None
    lens_model: str | None = None
    iso: int | None = None
    aperture: float | None = None
    exposure_time: str | None = None
    focal_length_mm: float | None = None
    exposure_compensation: float | None = None
    captured_at: str | None = None


class ImageMetrics(BaseModel):
    width: int
    height: int
    mean_brightness: float = Field(ge=0, le=1)
    contrast: float = Field(ge=0)
    shadow_ratio: float = Field(ge=0, le=1)
    highlight_ratio: float = Field(ge=0, le=1)
    sharpness_score: float = Field(ge=0)


class ImageInspection(BaseModel):
    exif: ExifInfo
    metrics: ImageMetrics
    model_image_data_url: str = Field(exclude=True, repr=False)


class SceneCandidate(BaseModel):
    profile_id: str
    label: str
    description: str
    subject: str
    environment: str
    default_motion: Literal["static", "slow", "fast", "unknown"]
    retrieval_terms: list[str] = Field(default_factory=list)
    score: float = 0
    evidence: list[str] = Field(default_factory=list)


class CameraProfile(BaseModel):
    device_type: Literal["camera"] = "camera"
    profile_id: str
    brand: str
    model: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    mount: str = "unknown"
    capability_level: Literal["catalog", "basic", "detailed"] = "detailed"
    checked_at: str = ""
    sensor_format: CameraFormat
    crop_factor: float | None = Field(default=None, gt=0)
    catalog_sensor_label: str = ""
    catalog_mount_labels: list[str] = Field(default_factory=list)
    catalog_sources: list[dict[str, str]] = Field(default_factory=list)
    native_iso_min: int | None = Field(default=None, ge=25)
    native_iso_max: int | None = Field(default=None, ge=100)
    recommended_auto_iso_max: int = Field(default=3200, ge=100)
    max_mechanical_shutter: int | None = Field(default=None, ge=1000)
    max_electronic_shutter: int | None = Field(default=None, ge=1000)
    ibis_stops: float | None = Field(default=None, ge=0)
    aperture_priority_name: str = "A/Av 光圈优先"
    shutter_priority_name: str = "S/Tv 快门优先"
    continuous_focus_name: str = "连续自动对焦"
    single_focus_name: str = "单次自动对焦"
    metering_name: str = "评价/矩阵测光（名称以机内为准）"
    source_url: str = ""
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def catalog_is_not_hardware_approval(self) -> CameraProfile:
        if self.capability_level == "catalog" and (
            self.mount != "unknown" or self.crop_factor is not None
            or any(value is not None for value in (
                self.native_iso_min, self.native_iso_max, self.max_mechanical_shutter,
                self.max_electronic_shutter, self.ibis_stops,
            ))
        ):
            raise ValueError("基础目录不得声明未经核验的硬件能力或卡口兼容")
        return self


class CameraLensProfile(BaseModel):
    lens_id: str
    display_name: str
    mount: str
    sensor_formats: list[CameraFormat]
    focal_min_mm: int = Field(ge=8, le=1200)
    focal_max_mm: int = Field(ge=8, le=1200)
    max_aperture_wide: float = Field(ge=0.7, le=32)
    max_aperture_tele: float = Field(ge=0.7, le=32)
    source_url: str
    checked_at: str
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_range(self) -> CameraLensProfile:
        if not self.sensor_formats or "不清楚" in self.sensor_formats or self.mount == "unknown":
            raise ValueError("镜头兼容目录必须明确原生卡口与成像圈画幅")
        if self.focal_min_mm > self.focal_max_mm:
            raise ValueError("镜头焦段范围倒置")
        if self.max_aperture_wide > self.max_aperture_tele:
            raise ValueError("镜头最大光圈端点顺序不正确")
        return self

    def conservative_aperture(self, focal_length: int) -> float:
        # 不伪造变焦镜头中间焦段的逐档光圈曲线。
        return (
            self.max_aperture_wide if focal_length == self.focal_min_mm else self.max_aperture_tele
        )


class EquipmentSettings(BaseModel):
    camera_lens: CameraLensProfile | None = None
    sensor_format: CameraFormat
    focal_length_mm: int | None = None
    equivalent_focal_length_mm: float | None = None
    max_aperture: float | None = None


class PhoneLens(BaseModel):
    lens_id: str
    name: str
    aperture: float | None = Field(default=None, gt=0)
    aperture_max: float | None = Field(default=None, gt=0)
    aperture_control: Literal["fixed", "variable", "unknown"] = "unknown"
    equivalent_focal_length_mm: float | None = Field(default=None, gt=0)
    modes: list[PhoneCaptureMode] = Field(default_factory=lambda: ["auto"])
    notes: list[str] = Field(default_factory=list)


class PhoneProfile(BaseModel):
    """手机原生相机能力，不用相机的机械快门／画幅参数冒充手机规格。"""

    device_type: Literal["phone"] = "phone"
    profile_id: str
    brand: str
    model: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    native_app: str = "原生相机"
    modes: list[PhoneCaptureMode] = Field(default_factory=lambda: ["auto"])
    pro_controls: list[Literal["iso", "shutter", "focus", "white_balance"]] = Field(
        default_factory=list
    )
    lenses: list[PhoneLens]
    source_urls: list[str] = Field(default_factory=list)
    checked_at: str
    region_scope: str
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_capabilities(self) -> PhoneProfile:
        ids = [lens.lens_id for lens in self.lenses]
        if "main" not in ids or len(ids) != len(set(ids)):
            raise ValueError("手机档案必须包含唯一主摄和不重复的镜头编号")
        if "auto" not in self.modes or (self.pro_controls and "pro" not in self.modes):
            raise ValueError("手机档案缺少照片模式或专业控制项对应的模式")
        for lens in self.lenses:
            if "auto" not in lens.modes or not set(lens.modes).issubset(self.modes):
                raise ValueError("镜头模式必须包含照片模式，且属于该手机已收录模式")
            if lens.aperture_max is not None and (
                lens.aperture is None or lens.aperture_max < lens.aperture
            ):
                raise ValueError("手机物理光圈范围不正确")
        return self


class SceneAnalysis(BaseModel):
    scene_type: str
    scene_label: str = ""
    subject: str
    environment: str
    lighting: str
    brightness: Literal["low", "medium", "high"]
    backlight: bool
    subject_motion: Literal["static", "slow", "fast", "unknown"]
    dynamic_range: Literal["low", "medium", "high"]
    desired_effects: list[str]
    confidence: float = Field(ge=0, le=1)
    notes: list[str] = Field(default_factory=list)
    recognition_evidence: list[str] = Field(default_factory=list)
    candidate_scenes: list[str] = Field(default_factory=list)
    retrieval_terms: list[str] = Field(default_factory=list)
    objects: list[SemanticObject] = Field(default_factory=list)
    main_subject_ids: list[str] = Field(default_factory=list)
    subject_status: Literal["selected", "ambiguous", "abstained"] = "abstained"
    composition_clues: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def subject_binding(self) -> SceneAnalysis:
        from vision_lab_tool.detector_queries import english_queries

        ids = [obj.object_id for obj in self.objects]
        if len(ids) != len(set(ids)) or len(self.main_subject_ids) != len(set(self.main_subject_ids)):
            raise ValueError("画面对象或主体 ID 重复。")
        if any(value not in ids for value in self.main_subject_ids):
            raise ValueError("主体必须引用画面对象。")
        if any(obj.parent_object_id and obj.parent_object_id not in ids for obj in self.objects):
            raise ValueError("部件必须引用存在的父对象。")
        if (self.subject_status == "selected") != bool(self.main_subject_ids):
            raise ValueError("主体选择状态与 ID 不一致。")
        english_queries([obj.query for obj in self.objects])
        return self


class KnowledgeHit(BaseModel):
    document_id: str
    title: str
    content: str
    source: str
    metadata: dict[str, str] = Field(default_factory=dict)
    score: float = 0


class CameraRecommendation(BaseModel):
    shooting_mode: str
    aperture: str
    shutter_speed: str
    iso: str
    exposure_compensation: str
    focus_mode: str
    metering_mode: str
    drive_mode: str
    white_balance: str
    reasons: list[str]
    risks: list[str]
    adjustments: list[str]
    confidence: float = Field(ge=0, le=1)
    validation_notes: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)


class PipelineResult(BaseModel):
    inspection: ImageInspection
    camera_profile: CameraProfile | PhoneProfile
    equipment_settings: EquipmentSettings | None = None
    scene: SceneAnalysis
    recommendation: CameraRecommendation
    knowledge_hits: list[KnowledgeHit]
    knowledge_mode: str = "legacy"
    knowledge_notes: list[str] = Field(default_factory=list)
    localization: MethodResult | None = None
    composition: CompositionAdvice | None = None
    composition_knowledge_hits: list[KnowledgeHit] = Field(default_factory=list)
