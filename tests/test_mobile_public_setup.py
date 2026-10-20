import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def setup_module():
    path = Path(__file__).resolve().parents[1] / 'scripts/configure_mobile_public.py'
    spec = importlib.util.spec_from_file_location('mobile_public_setup', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOKEN = 'fixture-token-12345678901234567890'


def test_only_mobile_token_changes(setup_module):
    original = 'CAMERA_AI_API_KEY=retain-private-key\nKNOWLEDGE_RETRIEVAL_MODE=managed\nMOBILE_API_TOKEN=old-token\nWEB_SESSION_SECRET=retain-session-secret\n'
    actual = setup_module.replace_mobile_token(original, TOKEN)
    assert 'CAMERA_AI_API_KEY=retain-private-key\n' in actual
    assert 'WEB_SESSION_SECRET=retain-session-secret\n' in actual
    assert 'KNOWLEDGE_RETRIEVAL_MODE=managed\n' in actual
    assert actual.count('MOBILE_API_TOKEN=') == 1
    assert actual.endswith('MOBILE_API_TOKEN=' + TOKEN + '\n')


@pytest.mark.parametrize('value', ['short', ' leading-space-token-1234567890', 'token-12345678901234567890\nBAD=value', '${OTHER_TOKEN}'])
def test_invalid_input_does_not_become_env_injection(setup_module, value):
    with pytest.raises(ValueError, match='invalid_mobile_token'):
        setup_module.replace_mobile_token('WEB_ORIGIN=https://115.29.241.181\n', value)


def test_duplicate_assignments_replaced_once(setup_module):
    actual = setup_module.replace_mobile_token('MOBILE_API_TOKEN=one\nexport MOBILE_API_TOKEN=two\n', TOKEN)
    assert actual == 'MOBILE_API_TOKEN=' + TOKEN + '\n'


def test_multiline_secret_requires_manual_review(setup_module):
    with pytest.raises(ValueError, match='multiline_mobile'):
        setup_module.replace_mobile_token('MOBILE_API_TOKEN="first-line\nsecond-line"\n', TOKEN)


def test_unknown_service_not_modified(setup_module):
    with pytest.raises(ValueError, match='compose_identity'):
        setup_module.compose({'Config': {'Labels': {'com.docker.compose.project': 'unrelated'}}})


def test_private_file_permissions_and_no_overwrite(setup_module, tmp_path):
    target = tmp_path / 'private.env'
    setup_module.save_private(target, b'private-fixture')
    with pytest.raises(FileExistsError):
        setup_module.save_private(target, b'overwrite')
    assert target.read_bytes() == b'private-fixture'
