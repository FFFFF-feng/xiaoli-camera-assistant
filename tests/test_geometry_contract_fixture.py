"""Synthetic wire examples shared with frontend/evaluation, not photo QA."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from camera_assistant.composition_models import CompositionAdvice, TargetBoard

FIXTURE = Path(__file__).parent / 'fixtures' / 'composition_contract_v1.json'


def test_frozen_wire_examples_keep_open_closed_legacy_and_failure_semantics():
    examples = json.loads(FIXTURE.read_text(encoding='utf-8'))
    for case in examples['valid']:
        board = TargetBoard.model_validate(case['board'])
        assert any(layer.role == 'main' for layer in board.layers)
        if case['id'] == 'continuous':
            assert board.layers[0].outline == []
            assert board.layout_mode == 'source_preserving'
        if case['id'] == 'legacy':
            assert board.render_basis == 'legacy' and board.layers[0].holes == []
        if case['id'] == 'silhouette_hole':
            assert len(board.layers[0].holes) == 1
    for case in examples['invalid']:
        with pytest.raises(ValidationError):
            TargetBoard.model_validate(case['board'])
    advice = CompositionAdvice.model_validate(examples['failure_advice'])
    assert not advice.proposals and advice.diagnostics[0].status == 'failed'
