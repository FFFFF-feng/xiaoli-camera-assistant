"""Composition suggestions with explicit actions and traceable knowledge references."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from camera_assistant.services.drawing_geometry import simple_outline


class CompositionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def validate_target_paths(value, outline: bool):
    paths = [value] if outline else value
    if not isinstance(paths, list) or (not outline and len(paths) > 96):
        raise ValueError("几何图形必须为点序列")
    for points in paths:
        if not isinstance(points, list) or not (3 if outline else 2) <= len(points) <= 64:
            raise ValueError("线条长度无效")
        for point in points:
            if (not isinstance(point, list) or len(point) != 2
                    or any(isinstance(n, bool) or not isinstance(n, (int, float))
                           or not math.isfinite(n) or not 0 <= n <= 1 for n in point)):
                raise ValueError("轮廓点须为0到1的数值坐标")
    return value


class SketchElement(CompositionModel):
    kind: Literal["person", "tree", "pet", "building", "mountain", "flower", "object"]
    label: str = Field(min_length=1, max_length=18)
    role: Literal["main", "context"]
    bbox: list[float] = Field(min_length=4, max_length=4)
    appearance: Literal["default", "standing", "seated", "walking", "cat", "dog", "bird",
                        "red_panda", "pine", "broadleaf", "cup", "bottle", "book", "camera"] = "default"
    facing: Literal["front", "left", "right"] = "front"
    description: str = Field(default="", max_length=70)
    source_bbox: list[float] | None = None
    identity_features: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("source_bbox", mode="before")
    @classmethod
    def source_region(cls, value: object) -> object:
        return None if value is None else cls.drawing_box(value)

    @field_validator("identity_features")
    @classmethod
    def visible_features(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 50 for value in values):
            raise ValueError("主体特征须为简短、非空的可见细节。")
        return list(dict.fromkeys(value.strip() for value in values))

    @field_validator("bbox", mode="before")
    @classmethod
    def drawing_box(cls, value: object) -> object:
        if (not isinstance(value, list) or len(value) != 4
                or any(isinstance(n, bool) or not isinstance(n, (int, float)) for n in value)):
            raise ValueError("示意位置必须为四个数值。")
        x1, y1, x2, y2 = value
        if (any(not math.isfinite(n) or not 0 <= n <= 1 for n in value)
                or x2 - x1 < .05 or y2 - y1 < .05):
            raise ValueError("示意对象必须完整位于画幅内且具有有效大小。")
        return value


class CompositionSketch(CompositionModel):
    aspect: Literal["portrait", "landscape", "square"]
    caption: str = Field(min_length=1, max_length=100)
    elements: list[SketchElement] = Field(min_length=1, max_length=6)
    horizon_y: float | None = Field(default=None, ge=0, le=1)
    camera_action: Literal["stay", "left", "right", "closer", "farther", "lower", "higher"]
    camera_instruction: str = Field(min_length=1, max_length=100)
    theme: str = Field(default="", max_length=40)
    mood: str = Field(default="", max_length=40)
    narration: str = Field(default="", max_length=160)
    space_note: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def has_subject(self) -> CompositionSketch:
        if not any(element.role == "main" for element in self.elements):
            raise ValueError("示意图需要明确的主体。")
        return self


class FramingPlan(CompositionModel):
    diagnosis: str = Field(min_length=1, max_length=160)
    visual_priority: str = Field(min_length=1, max_length=100)
    placement: str = Field(min_length=1, max_length=120)
    scale: str = Field(min_length=1, max_length=100)
    negative_space: str = Field(min_length=1, max_length=120)
    edge_check: str = Field(min_length=1, max_length=120)
    background_control: str = Field(min_length=1, max_length=120)
    success_check: str = Field(min_length=1, max_length=140)

    @field_validator("*")
    @classmethod
    def nonblank_instruction(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("取景检查项不能为空白。")
        return value.strip()


class TargetLayer(CompositionModel):
    label: str = Field(min_length=1, max_length=30)
    kind: str = Field(min_length=1, max_length=30, description="实际对象类别，如rocket/tower/light；平整背景色块为background")
    role: Literal["main", "foreground", "background", "prop"]
    depth: int = Field(ge=0, le=9)
    bbox: list[float]
    color: Literal["slate", "blue", "ochre", "sage", "rose"] = "slate"
    representation: Literal["silhouette", "context_lines"] = "silhouette"
    outline: list[list[float]] = Field(min_length=0, max_length=64)
    contours: list[list[list[float]]] = Field(default_factory=list, max_length=12)
    outline_style: Literal["angular", "curved"] = "angular"
    details: list[list[list[float]]] = Field(default_factory=list, max_length=96)
    identity_features: list[str] = Field(default_factory=list, max_length=6)
    evidence_photo_ids: list[Literal["photo1", "photo2", "photo3", "photo4", "photo5", "photo6"]] = Field(min_length=1, max_length=6)
    certainty: Literal["observed", "approximate"] = "observed"
    source_object_id: str | None = Field(default=None, pattern=r"^object[1-6]$")
    source_bbox: list[float] | None = None
    source_details: list[list[list[float]]] | None = None
    mobility: Literal["fixed", "movable", "unknown"] = "unknown"

    @field_validator("source_bbox", mode="before")
    @classmethod
    def valid_source_box(cls, value):
        return None if value is None else cls.valid_box(value)

    @field_validator("kind")
    @classmethod
    def object_category(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("对象类别必须为简短可读文字")
        return value.strip().casefold()

    @field_validator("bbox", mode="before")
    @classmethod
    def valid_box(cls, value):
        if (not isinstance(value, list) or len(value) != 4 or any(
            isinstance(n, bool) or not isinstance(n, (int, float))
            or not math.isfinite(n) or not 0 <= n <= 1 for n in value
        ) or value[2]-value[0] < .005 or value[3]-value[1] < .005):
            raise ValueError("目标对象位置需要有效的0到1包围盒")
        return value

    @field_validator("outline", "details", mode="before")
    @classmethod
    def numeric_geometry(cls, value, info):
        if info.field_name == "outline" and value == [] and info.data.get("representation") == "context_lines":
            return value
        return validate_target_paths(value, info.field_name == "outline")

    @field_validator("source_details", mode="before")
    @classmethod
    def valid_source_details(cls, value):
        return None if value is None else validate_target_paths(value, False)

    @field_validator("contours", mode="before")
    @classmethod
    def separate_silhouettes(cls, value):
        if not isinstance(value, list) or len(value) > 12:
            raise ValueError("物体分部轮廓数量无效")
        for path in value:
            validate_target_paths(path, True)
            if not simple_outline(path):
                raise ValueError("物体分部轮廓不能自交")
        return value

    @model_validator(mode="after")
    def meaningful_outline(self):
        if self.kind == "background" and self.role != "background":
            raise ValueError("背景色块不能代替主体或前景")
        if self.representation == "context_lines":
            if self.role == "main" or self.outline or self.contours or not self.details:
                raise ValueError("环境线条不能代替主体，须有实际线条且不生成填充轮廓")
            return self
        area = abs(sum(a[0]*b[1] - b[0]*a[1]
                       for a, b in zip(self.outline, self.outline[1:] + self.outline[:1]))) / 2
        if area < .01:
            raise ValueError("主体轮廓不能退化为一条线")
        if not simple_outline(self.outline):
            raise ValueError("主体外轮廓不能自交、重复折返或重叠")
        return self


class CompositionChange(CompositionModel):
    problem: str = Field(min_length=1, max_length=140)
    adjustment: str = Field(min_length=1, max_length=140)
    benefit: str = Field(min_length=1, max_length=140)


class ObservedPart(CompositionModel):
    label: str = Field(min_length=1, max_length=30)
    bbox: list[float]
    kind: Literal["flower", "leaf", "feature"] = "feature"

    @field_validator("bbox", mode="before")
    @classmethod
    def valid_part_box(cls, value):
        return TargetLayer.valid_box(value)


class ObservedObject(TargetLayer):
    """A model-estimated visible silhouette, never a segmentation ground truth."""

    object_id: str = Field(pattern=r"^object[1-6]$")
    parts: list[ObservedPart] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def parts_inside_object(self):
        if len({tuple(part.bbox) for part in self.parts}) != len(self.parts):
            raise ValueError("主体分部不能重复")
        for part in self.parts:
            if not (self.bbox[0] <= part.bbox[0] < part.bbox[2] <= self.bbox[2]
                    and self.bbox[1] <= part.bbox[1] < part.bbox[3] <= self.bbox[3]):
                raise ValueError("主体分部必须位于已观察物体范围内")
        return self

    @field_validator("kind")
    @classmethod
    def canonical_kind(cls, value):
        return {"人物": "person", "人": "person", "动物": "pet", "小熊猫": "pet",
                "树": "tree", "树木": "tree", "花": "flower", "建筑": "building",
                "塔架": "tower", "火箭": "rocket"}.get(value, value)


class ObservedScene(CompositionModel):
    reference_photo_id: Literal["photo1"] = "photo1"
    objects: list[ObservedObject] = Field(min_length=1, max_length=6)
    limitations: list[str] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def distinct_objects(self):
        if len({obj.object_id for obj in self.objects}) != len(self.objects):
            raise ValueError("原始物体编号不能重复")
        if not any(obj.role == "main" and obj.kind != "background" for obj in self.objects):
            raise ValueError("原始场景需要可辨认的主体")
        if any("photo1" not in obj.evidence_photo_ids for obj in self.objects):
            raise ValueError("原始物体必须在主图中可见")
        return self


class TargetBoard(CompositionModel):
    aspect: Literal["portrait", "landscape", "square"]
    reference_photo_id: Literal["photo1", "photo2", "photo3", "photo4", "photo5", "photo6"]
    intent: str = Field(min_length=1, max_length=100)
    narration: str = Field(default="", max_length=160)
    distance_relation: Literal["closer", "farther", "similar", "unknown"]
    distance_instruction: str = Field(min_length=1, max_length=160)
    layers: list[TargetLayer] = Field(min_length=1, max_length=6)
    changes: list[CompositionChange] = Field(min_length=1, max_length=3)
    limitations: list[str] = Field(min_length=1, max_length=5)
    render_basis: Literal["legacy", "source_geometry"] = "legacy"
    layout_mode: Literal["schematic", "crop_projection"] = "schematic"
    source_photo_aspect: float | None = Field(default=None, gt=0, le=100)

    @model_validator(mode="after")
    def contains_main(self):
        if not any(layer.role == "main" for layer in self.layers):
            raise ValueError("推荐分镜必须包含主体")
        return self


class CompositionProposal(CompositionModel):
    action_type: Literal["crop", "camera_position", "focal_length", "reshoot"]
    goal: str = Field(min_length=1)
    actions: list[str] = Field(min_length=1)
    reasons: list[str] = Field(min_length=1)
    tradeoffs: list[str] = Field(min_length=1)
    conditions: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    knowledge_ids: list[str] = Field(default_factory=list)
    crop_bbox: list[float] | None = None
    sketch: CompositionSketch | None = None
    framing_plan: FramingPlan | None = None
    storyboard: TargetBoard | None = None

    @field_validator("storyboard", mode="before")
    @classmethod
    def optional_board(cls, value):
        if value is None:
            return None
        try:
            return TargetBoard.model_validate(value)
        except (ValidationError, ValueError, TypeError):
            return None

    @field_validator("framing_plan", mode="before")
    @classmethod
    def optional_framing_plan(cls, value: object) -> FramingPlan | None:
        if value is None:
            return None
        try:
            return FramingPlan.model_validate(value)
        except (ValidationError, TypeError, ValueError):
            return None

    @field_validator("sketch", mode="before")
    @classmethod
    def keep_text_if_drawing_invalid(cls, value: object) -> CompositionSketch | None:
        # A malformed optional drawing must not discard otherwise useful photography advice.
        if value is None:
            return None
        try:
            return CompositionSketch.model_validate(value)
        except (ValidationError, TypeError, ValueError):
            return None

    @field_validator("goal")
    @classmethod
    def nonblank_goal(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("构图目标不能为空白。")
        return value.strip()

    @field_validator("actions", "reasons", "tradeoffs", "conditions", "limitations", "knowledge_ids")
    @classmethod
    def nonblank_items(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("构图方案字段不能包含空白条目。")
        return list(dict.fromkeys(value.strip() for value in values))

    @field_validator("crop_bbox", mode="before")
    @classmethod
    def numeric_box(cls, value: object) -> object:
        if value is not None and (
            not isinstance(value, list)
            or len(value) != 4
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in value)
        ):
            raise ValueError("裁切框必须是四个数值组成的归一化坐标。")
        return value

    @field_validator("crop_bbox")
    @classmethod
    def normalized_box(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return value
        if any(not math.isfinite(item) or not 0 <= item <= 1 for item in value):
            raise ValueError("裁切框必须使用 0 到 1 的有限坐标。")
        if value[0] >= value[2] or value[1] >= value[3]:
            raise ValueError("裁切框不能倒置或没有面积。")
        return value

    @model_validator(mode="after")
    def crop_action(self) -> CompositionProposal:
        if self.crop_bbox is not None and self.action_type != "crop":
            raise ValueError("只有裁切方案可以包含裁切框。")
        return self


class CompositionAdvice(CompositionModel):
    status: Literal["grounded", "unverified", "unavailable", "demo"]
    observations: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    proposals: list[CompositionProposal] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
