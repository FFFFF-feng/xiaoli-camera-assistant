"""Explicit wire-to-internal bbox units; never infer units from returned values.

GLM-V grounding contract: https://github.com/zai-org/GLM-V#grounding
Model profiles are selected BEFORE the request. Internal models remain 0..1 xyxy.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from camera_assistant.config import Settings

UNITS = frozenset({'normalized_0_1', 'normalized_0_1000'})
GLM_GROUNDING_MODEL = re.compile(r'glm-4\.(?:1v|5v|6v)(?:-[a-z0-9]+)*', re.IGNORECASE)


class ObservationCoordinateError(ValueError):
    """Only fixed codes and schema paths, never provider data, enter diagnostics."""
    def __init__(self, code: str, field_path: str):
        self.code = code
        self.field_path = field_path
        super().__init__('识别坐标单位不符合请求协议' if code == 'recognition_coordinate_unit_invalid'
                         else '物体位置字段不符合要求')


@dataclass(frozen=True)
class ObservationCoordinates:
    unit: str = 'normalized_0_1'

    def __post_init__(self):
        if self.unit not in UNITS:
            raise ValueError('不支持的识别坐标单位')

    @property
    def scale(self) -> int:
        return 1000 if self.unit == 'normalized_0_1000' else 1

    @property
    def rule(self) -> str:
        if self.scale == 1000:
            return ('bbox使用0到1000整数xyxy：[x1,y1,x2,y2]，左上[0,0]、右下[1000,1000]；'
                    'x按方向校正后photo1的宽归一化乘1000，y按其高归一化乘1000，'
                    '不是图像像素、0到1小数、百分数或xywh。x1<x2、y1<y2，宽高各至少5。'
                    '只能使用JSON整数，不接受字符串、布尔值、嵌套点对或混合单位。')
        return ('bbox使用0到1归一化xyxy：[x1,y1,x2,y2]，左上[0,0]、右下[1,1]；'
                'x相对于方向校正后photo1的宽，y相对于其高。x1<x2、y1<y2，宽高各至少0.005。'
                '只能使用JSON数值，不接受字符串、布尔值、嵌套点对、图像像素、百分数、'
                '0到1000方纸坐标或[x,y,width,height]，不混合单位。')

    @property
    def bbox_schema(self) -> dict:
        return {'type': 'array', 'items': {'type': 'integer' if self.scale == 1000 else 'number',
                                          'minimum': 0, 'maximum': self.scale},
                'minItems': 4, 'maxItems': 4, 'description': self.rule}

    @property
    def full_frame(self) -> str:
        return f'[0,0,{self.scale},{self.scale}]'

    def normalize_box(self, value, field_path: str) -> list[float]:
        def invalid():
            return ObservationCoordinateError('recognition_bbox_invalid', field_path)
        if (not isinstance(value, list) or len(value) != 4 or any(
                type(n) not in (int, float) or not 0 <= n <= self.scale or not math.isfinite(n)
                or (self.scale == 1000 and not float(n).is_integer()) for n in value)):
            raise invalid()
        minimum = .005 * self.scale
        if any(extent < minimum and not math.isclose(extent, minimum, rel_tol=0, abs_tol=1e-12*self.scale)
               for extent in (value[2]-value[0], value[3]-value[1])):
            raise invalid()
        return [n / self.scale for n in value]

    def normalize_answer(self, answer):
        """Convert main/part boxes exactly once. Keep all other evidence untouched.

        An optional response declaration must agree with the preselected contract.
        Missing declarations use the request's fixed profile (legacy compatibility).
        Optional malformed parts remain discardable by prepare_observation, never
        accepted accidentally as already-normalized boxes in a 1000-unit response.
        """
        if not isinstance(answer, dict):
            return answer  # Existing strict parser supplies the structural error.
        if 'coordinate_unit' in answer and answer['coordinate_unit'] != self.unit:
            raise ObservationCoordinateError('recognition_coordinate_unit_invalid', 'coordinate_unit')
        clean = {key: value for key, value in answer.items() if key != 'coordinate_unit'}
        rows = clean.get('objects')
        if not isinstance(rows, list):
            return clean
        objects = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                objects.append(row)
                continue
            path = f'objects.{index}.bbox'
            converted = {**row}
            # Missing fields must stay missing for the existing schema diagnostics.
            if 'bbox' in row:
                converted['bbox'] = self.normalize_box(row['bbox'], path)
            parts = row.get('parts')
            if isinstance(parts, list):
                converted['parts'] = []
                for part_index, part in enumerate(parts[:8]):
                    if not isinstance(part, dict) or 'bbox' not in part:
                        converted['parts'].append(part)
                        continue
                    try:
                        box = self.normalize_box(part['bbox'], f'objects.{index}.parts.{part_index}.bbox')
                    except ObservationCoordinateError:
                        box = None  # Existing optional-part policy discards it with a fixed note.
                    converted['parts'].append({**part, 'bbox': box})
                # Preserve the existing over-limit diagnostic without copying unbounded parts.
                if len(parts) > 8:
                    converted['parts'].append(None)
            objects.append(converted)
        return {**clean, 'objects': objects}


def observation_coordinates(settings: Settings) -> ObservationCoordinates:
    unit = settings.observation_coordinate_unit
    if unit == 'model_default':
        name = settings.vision_model.rsplit('/', 1)[-1]
        # Unknown models keep the explicit legacy 0..1 contract. Never switch
        # based on API host, preset, bbox magnitudes, pixels, or a model's claim.
        unit = 'normalized_0_1000' if GLM_GROUNDING_MODEL.fullmatch(name) else 'normalized_0_1'
    return ObservationCoordinates(unit)
