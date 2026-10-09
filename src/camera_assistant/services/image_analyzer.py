from __future__ import annotations

import base64
import io
from fractions import Fraction
from typing import ClassVar

import numpy as np
from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

from camera_assistant.models import ExifInfo, ImageInspection, ImageMetrics


class ImageValidationError(ValueError):
    """用户上传的图片无法安全处理。"""


class ImageAnalyzer:
    SUPPORTED_FORMATS: ClassVar[set[str]] = {"JPEG", "PNG"}

    def __init__(self, max_image_mb: int = 15) -> None:
        self.max_bytes = max_image_mb * 1024 * 1024

    def analyze(self, content: bytes) -> ImageInspection:
        if not content:
            raise ImageValidationError("图片内容为空，请重新选择原图。")
        if len(content) > self.max_bytes:
            raise ImageValidationError(
                f"图片超过 {self.max_bytes // 1024 // 1024} MB，请选择尺寸更小的原图。"
            )

        try:
            raw_image = Image.open(io.BytesIO(content))
            raw_image.verify()
            raw_image = Image.open(io.BytesIO(content))
        except (UnidentifiedImageError, OSError) as exc:
            raise ImageValidationError("无法识别该文件，请上传 JPG、JPEG 或 PNG 图片。") from exc

        if raw_image.format not in self.SUPPORTED_FORMATS:
            raise ImageValidationError("当前版本只支持 JPG、JPEG 和 PNG 图片。")

        exif = self._extract_exif(raw_image)
        image = ImageOps.exif_transpose(raw_image).convert("RGB")
        metrics = self._calculate_metrics(image)
        data_url = self._make_model_image(image)
        return ImageInspection(exif=exif, metrics=metrics, model_image_data_url=data_url)

    def _calculate_metrics(self, image: Image.Image) -> ImageMetrics:
        preview = image.copy()
        preview.thumbnail((640, 640))
        gray = np.asarray(preview.convert("L"), dtype=np.float32)
        vertical = np.diff(gray, axis=0)
        horizontal = np.diff(gray, axis=1)
        sharpness = float(np.var(vertical) + np.var(horizontal))

        return ImageMetrics(
            width=image.width,
            height=image.height,
            mean_brightness=round(float(gray.mean() / 255), 4),
            contrast=round(float(gray.std() / 255), 4),
            shadow_ratio=round(float(np.mean(gray <= 28)), 4),
            highlight_ratio=round(float(np.mean(gray >= 245)), 4),
            sharpness_score=round(sharpness, 2),
        )

    def _extract_exif(self, image: Image.Image) -> ExifInfo:
        try:
            raw_exif = image.getexif()
        except (AttributeError, OSError):
            return ExifInfo()

        values: dict[str, object] = {}
        for tag_id, value in raw_exif.items():
            tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
            values[tag_name] = value

        return ExifInfo(
            camera_make=self._text(values.get("Make")),
            camera_model=self._text(values.get("Model")),
            lens_model=self._text(values.get("LensModel")),
            iso=self._integer(values.get("ISOSpeedRatings") or values.get("PhotographicSensitivity")),
            aperture=self._number(values.get("FNumber")),
            exposure_time=self._exposure(values.get("ExposureTime")),
            focal_length_mm=self._number(values.get("FocalLength")),
            exposure_compensation=self._number(values.get("ExposureBiasValue")),
            captured_at=self._text(values.get("DateTimeOriginal") or values.get("DateTime")),
        )

    @staticmethod
    def _make_model_image(image: Image.Image) -> str:
        model_image = image.copy()
        model_image.thumbnail((1600, 1600))
        buffer = io.BytesIO()
        model_image.save(buffer, format="JPEG", quality=88, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    @staticmethod
    def _number(value: object) -> float | None:
        if value is None:
            return None
        try:
            return round(float(value), 3)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    @staticmethod
    def _integer(value: object) -> int | None:
        if isinstance(value, (tuple, list)) and value:
            value = value[0]
        number = ImageAnalyzer._number(value)
        return int(number) if number is not None else None

    @staticmethod
    def _text(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip().strip("\x00")
        return text or None

    @staticmethod
    def _exposure(value: object) -> str | None:
        number = ImageAnalyzer._number(value)
        if number is None or number <= 0:
            return None
        if number >= 1:
            return f"{number:g}s"
        fraction = Fraction(number).limit_denominator(8000)
        return f"{fraction.numerator}/{fraction.denominator}s"
