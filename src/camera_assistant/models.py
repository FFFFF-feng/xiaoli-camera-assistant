from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

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
    focal_length_mm: int | None = Field(default=None, ge=8, le=1200)
    max_aperture: float | None = Field(default=None, ge=0.7, le=32)
    device_type: Literal["camera", "phone"] = "camera"
    phone_profile_id: str = "generic_phone"
    phone_capture_mode: PhoneCaptureMode = "auto"
    phone_lens_id: str = "main"
    phone_pro_controls_confirmed: bool = False


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
    sensor_format: CameraFormat
    crop_factor: float = Field(gt=0)
    native_iso_min: int = Field(ge=25)
    native_iso_max: int = Field(ge=100)
    recommended_auto_iso_max: int = Field(ge=100)
    max_mechanical_shutter: int = Field(ge=1000)
    max_electronic_shutter: int | None = Field(default=None, ge=1000)
    ibis_stops: float = Field(default=0, ge=0)
    aperture_priority_name: str
    shutter_priority_name: str
    continuous_focus_name: str
    single_focus_name: str
    metering_name: str
    source_url: str = ""
    notes: list[str] = Field(default_factory=list)


class PhoneLens(BaseModel):
    lens_id: str
    name: str
    aperture: float | None = Field(default=None, gt=0)
    aperture_control: Literal["fixed", "variable", "unknown"] = "unknown"
    equivalent_focal_length_mm: float | None = Field(default=None, gt=0)
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


class PipelineResult(BaseModel):
    inspection: ImageInspection
    camera_profile: CameraProfile | PhoneProfile
    scene: SceneAnalysis
    recommendation: CameraRecommendation
    knowledge_hits: list[KnowledgeHit]
    knowledge_mode: str = "legacy"
    knowledge_notes: list[str] = Field(default_factory=list)
