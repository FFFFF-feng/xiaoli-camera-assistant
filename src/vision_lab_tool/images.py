from __future__ import annotations

import base64
import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from camera_assistant.services.image_analyzer import ImageAnalyzer, ImageValidationError
from vision_lab_tool.models import VisibleObject


@dataclass
class PreparedImage:
    corrected: Image.Image
    sent_bytes: bytes
    original_size: tuple[int, int]
    original_format: str
    original_sha256: str
    corrected_sha256: str
    longest_edge: int
    quality: int
    exif: dict

    @property
    def sent_size(self):
        with Image.open(io.BytesIO(self.sent_bytes)) as image:
            return image.size

    @property
    def data_url(self):
        return "data:image/jpeg;base64," + base64.b64encode(self.sent_bytes).decode("ascii")

    def metadata(self):
        return {
            "original_size": self.original_size,
            "corrected_size": self.corrected.size,
            "sent_size": self.sent_size,
            "original_format": self.original_format,
            "sent_format": "JPEG",
            "longest_edge": self.longest_edge,
            "quality": self.quality,
            "original_sha256": self.original_sha256,
            "corrected_sha256": self.corrected_sha256,
            "sent_sha256": hashlib.sha256(self.sent_bytes).hexdigest(),
            "sent_bytes": len(self.sent_bytes),
            "coordinate_system": "exif-corrected normalized xyxy",
        }


def prepare_image(content: bytes, longest_edge: int = 1600, quality: int = 88) -> PreparedImage:
    analyzer = ImageAnalyzer(max_image_mb=15)
    if not content or len(content) > analyzer.max_bytes:
        raise ImageValidationError("图片为空或超过 15 MB 上限。")
    if not 1 <= longest_edge <= 4096:
        raise ImageValidationError("最长边必须为 1～4096 像素。")
    if not 20 <= quality <= 100:
        raise ImageValidationError("JPEG 质量必须为 20～100。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                source.verify()
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in analyzer.SUPPORTED_FORMATS:
                    raise ImageValidationError("真实文件格式仅支持 JPG/JPEG/PNG。")
                original_size, original_format = source.size, source.format
                exif = analyzer._extract_exif(source).model_dump(mode="json")
                corrected = ImageOps.exif_transpose(source).convert("RGB")
                corrected.info.clear()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        ValueError,
    ) as exc:
        raise ImageValidationError("无法解码或安全处理图片，请上传 JPG/JPEG/PNG。") from exc
    sent = corrected.copy()
    sent.thumbnail((longest_edge, longest_edge), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    sent.save(buffer, "JPEG", quality=quality, optimize=True)
    return PreparedImage(
        corrected,
        buffer.getvalue(),
        original_size,
        original_format,
        hashlib.sha256(content).hexdigest(),
        hashlib.sha256(str(corrected.size).encode() + corrected.tobytes()).hexdigest(),
        longest_edge,
        quality,
        exif,
    )


def overlay(image: Image.Image, objects: list[VisibleObject]) -> Image.Image:
    result = image.copy()
    draw = ImageDraw.Draw(result)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", max(14, image.width // 65))
    except OSError:
        font = ImageFont.load_default()
    for obj in objects:
        if obj.bbox is None:
            continue
        x1, y1, x2, y2 = obj.bbox
        draw.rectangle(
            (x1 * image.width, y1 * image.height, x2 * image.width, y2 * image.height),
            outline="#f57b42",
            width=max(2, image.width // 400),
        )
        draw.text(
            (x1 * image.width, y1 * image.height),
            f"{obj.object_id}: {obj.label}",
            font=font,
            fill="#f57b42",
            stroke_width=1,
            stroke_fill="white",
        )
    return result
