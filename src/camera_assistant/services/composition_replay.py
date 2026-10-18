"""Opt-in ignored local diagnostics: no photos, requests, secrets or remote errors."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

VERSION = "composition-replay-v2"


def validation_fields(error: Exception) -> list[dict]:
    if not isinstance(error, ValidationError):
        return []
    # Only schema keys and bounded numeric indices enter diagnostics. Never copy
    # input, ctx, provider values, or an arbitrary remote response into a record.
    allowed = {'objects', 'object_id', 'label', 'kind', 'role', 'depth', 'bbox', 'mobility',
               'identity_features', 'evidence_photo_ids', 'limitations', 'reference_photo_id',
               'parts', 'color', 'scene_mode', 'certainty', 'outline', 'details', 'contours',
               'representation', 'source_details', 'source_bbox'}
    rows = []
    for issue in error.errors(include_input=False, include_url=False)[:16]:
        path = [str(p) if isinstance(p, int) and 0 <= p <= 96 else p if p in allowed else 'unknown'
                for p in issue['loc']]
        rows.append({'field_path': '.'.join(path)[:120] or 'unknown',
                     'type': issue['type'] if issue['type'] in {'missing', 'literal_error', 'value_error',
                         'extra_forbidden', 'too_long', 'too_short', 'string_pattern_mismatch',
                         'list_type', 'int_type', 'int_parsing', 'float_type', 'string_type'} else 'invalid'})
    return rows


class ReplayRecord:
    def __init__(self, inspection):
        self.path = None
        self.value = {}
        if os.environ.get('CAMERA_AI_COMPOSITION_REPLAY') != '1':
            return
        try:
            raw = base64.b64decode(inspection.model_image_data_url.split(',', 1)[1], validate=True)
            root = Path(__file__).resolve().parents[3] / '.tmp' / 'composition-replay'
            root.mkdir(parents=True, exist_ok=True)
            self.path = root / f'{uuid4().hex}.json'
            self.value = {'version': VERSION, 'model_image_sha256': hashlib.sha256(raw).hexdigest(),
                          'width': inspection.metrics.width, 'height': inspection.metrics.height,
                          'attempts': []}
        except (OSError, ValueError, IndexError):
            self.path = None

    def update(self, **fields):
        if self.path is None:
            return
        self.value.update(fields)
        try:
            self.path.write_text(json.dumps(self.value, ensure_ascii=False, indent=2), encoding='utf-8')
        except OSError:
            pass  # Diagnostic IO must not change pipeline success or retry policy.

    def issue(self, attempt: int, error: Exception):
        self.value.setdefault('attempts', []).append({'attempt': attempt, 'issues': validation_fields(error)})
        self.update(stage='recognition', status='invalid')

    def observation(self, answer, attempt):
        """Keep only bounded relation inputs, including before metadata validation.

        Free text, unknown keys, provider geometry and credentials are omitted.
        This projection diagnoses enum/relation failures; valid metadata below
        remains the full replay input for pixel processing.
        """
        if not isinstance(answer, dict):
            self.update(observation_type='not_object')
            return
        enums = {'scene_mode': {'objects', 'continuous'},
                 'kind': {'person', 'pet', 'cat', 'dog', 'bird', 'flower', 'tree', 'object',
                          'building', 'mountain', 'landscape', 'architecture', 'background', 'cup', 'lake', 'water'},
                 'role': {'main', 'foreground', 'background', 'prop'},
                 'mobility': {'fixed', 'movable', 'unknown'}}
        def safe(key, value):
            return value if isinstance(value, str) and value in enums[key] else 'invalid_or_missing'
        objects = []
        rows = answer.get('objects')
        for row in rows[:4] if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                objects.append({'type': 'not_object'})
                continue
            obj = {key: safe(key, row.get(key)) for key in ('kind', 'role', 'mobility')}
            box = row.get('bbox')
            obj['bbox'] = box if (isinstance(box, list) and len(box) == 4 and all(
                type(n) in (int, float) and math.isfinite(n) and abs(n) <= 10000 for n in box)) else 'invalid_or_missing'
            objects.append(obj)
        self.value.setdefault('observations', []).append({'attempt': attempt,
            'scene_mode': safe('scene_mode', answer.get('scene_mode')), 'objects': objects})
        self.update(stage='recognition', status='received')

    def metadata(self, scene):
        from camera_assistant.services.pixel_contours import (
            _ALGORITHM_VERSION,
            DETAIL_EDGE,
            MAX_EDGE,
        )
        from camera_assistant.services.scene_structure import STRUCTURE_VERSION
        self.update(stage='contours', status='started', metadata=scene.model_dump(),
                    processing={'algorithm': _ALGORITHM_VERSION, 'max_edge': MAX_EDGE, 'detail_edge': DETAIL_EDGE,
                                'pet_iterations': 5, 'object_iterations': 2,
                                'scene_structure': STRUCTURE_VERSION})
