"""Unit configuration is checked before launching, without credentials or calls."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('coordinate_launcher_check', ROOT / 'scripts/launch_web.py')
web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web)


@pytest.mark.parametrize('unit', ['model_default', 'normalized_0_1', 'normalized_0_1000'])
def test_launcher_checks_units_without_loading_secrets_or_model(tmp_path, monkeypatch, unit):
    from camera_assistant.config import Settings
    monkeypatch.setattr(web, 'ROOT', tmp_path)
    monkeypatch.setattr(web.os, 'environ', {'CAMERA_AI_OBSERVATION_COORDINATE_UNIT': unit})
    monkeypatch.setattr(Settings, 'from_env', lambda: pytest.fail('preflight must not load credentials'))
    web.check_observation_coordinates()


def test_bad_local_option_fails_without_echoing_user_values(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'ROOT', tmp_path)
    monkeypatch.setattr(web.os, 'environ', {})
    (tmp_path / '.env').write_text('CAMERA_AI_OBSERVATION_COORDINATE_UNIT=SECRET_INVALID_VALUE\n')
    with pytest.raises(web.LaunchError) as failure:
        web.check_observation_coordinates()
    assert 'SECRET_INVALID_VALUE' not in str(failure.value)
    assert '坐标单位配置无效' in str(failure.value)


def test_launcher_environment_override_wins_and_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(web, 'ROOT', tmp_path)
    monkeypatch.setattr(web.os, 'environ', {'CAMERA_AI_OBSERVATION_COORDINATE_UNIT': 'normalized_0_1'})
    (tmp_path / '.env').write_text('CAMERA_AI_OBSERVATION_COORDINATE_UNIT=pixels\n')
    web.check_observation_coordinates()
