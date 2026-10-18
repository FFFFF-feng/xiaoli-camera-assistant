"""Opt-in ignored local diagnostics: no photos, requests, secrets or remote errors."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
from pathlib import Path
from threading import RLock
from uuid import uuid4

from pydantic import ValidationError

VERSION = "composition-replay-v3"
REPLAY_ROOT = Path(__file__).resolve().parents[3] / '.tmp' / 'composition-replay'
MAX_RECORDS = 32
MAX_RECORD_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
_LOCK = RLock()


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
            from camera_assistant.services.composition_trace import current_trace_id
            root = REPLAY_ROOT
            root.mkdir(parents=True, exist_ok=True)
            self.path = root / f'{uuid4().hex}.json'
            self.value = {'version': VERSION, 'trace_id': current_trace_id(), 'record_id': self.path.stem,
                          'model_image_sha256': hashlib.sha256(raw).hexdigest(),
                          'width': inspection.metrics.width, 'height': inspection.metrics.height,
                          'attempts': []}
        except (OSError, ValueError, IndexError):
            self.path = None

    def update(self, **fields):
        if self.path is None:
            return
        allowed = {'stage', 'status', 'code', 'object_id', 'internal_stage', 'observation_type',
                   'metadata', 'processing', 'extracted'}
        self.value.update({key: value for key, value in fields.items() if key in allowed})
        try:
            data = json.dumps(self.value, ensure_ascii=False, indent=2).encode('utf-8')
            if len(data) > MAX_RECORD_BYTES:
                self.value.pop('extracted', None)
                self.value['extracted_omitted'] = 'record_size_limit'
                data = json.dumps(self.value, ensure_ascii=False, indent=2).encode('utf-8')
            if len(data) > MAX_RECORD_BYTES:
                return  # Never persist an oversized input or disrupt the business result.
            with _LOCK:
                temporary = self.path.with_suffix('.tmp')
                temporary.write_bytes(data)
                temporary.replace(self.path)
                files = sorted((p for p in self.path.parent.glob('*.json')
                                if re.fullmatch(r'[a-f0-9]{32}\.json', p.name)),
                               key=lambda p: p.stat().st_mtime_ns)
                total = sum(p.stat().st_size for p in files)
                while len(files) > MAX_RECORDS or total > MAX_TOTAL_BYTES:
                    oldest = files.pop(0)
                    if oldest == self.path:
                        break
                    total -= oldest.stat().st_size
                    oldest.unlink()
        except (OSError, ValueError, TypeError):
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
                          'building', 'mountain', 'landscape', 'architecture', 'background', 'cup', 'lake', 'water',
                          'ball', 'bottle', 'camera', 'book'},
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
