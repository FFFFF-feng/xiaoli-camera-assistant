import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest


@pytest.fixture
def release(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'scripts/deploy_device_options_release.py'
    spec = importlib.util.spec_from_file_location('device_release', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OLD = tmp_path / 'old'
    module.OLD.mkdir()
    return module


def archive(release, tmp_path, *, extra=None, duplicate=False):
    files = {name: b'reviewed-payload' for name in release.RUNTIME}
    if extra:
        files[extra] = b'not allowed'
    manifest = {'schema': 1, 'release': 'device-options-20261020', 'files': {
        name: {'before': None, 'after': release.digest(data), 'size': len(data)}
        for name, data in files.items()}}
    files['manifest.json'] = json.dumps(manifest).encode()
    path = tmp_path / 'release.tar.gz'
    with tarfile.open(path, 'w:gz') as package:
        for name, data in list(files.items()) + (list(files.items())[:1] if duplicate else []):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            package.addfile(member, io.BytesIO(data))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('name', ['../secret', '/etc/passwd', 'deploy/.env', 'data/knowledge.db',
                                  'mobile/dist/assets/../../secret.js', 'mobile/dist/assets/key.env'])
def test_private_and_unsafe_paths_rejected(release, name):
    assert not release.allowed(name)


def test_reviewed_overlay_readable(release, tmp_path):
    path, checksum = archive(release, tmp_path)
    manifest, files = release.read_overlay(path, checksum)
    assert set(files) == release.RUNTIME == set(manifest['files'])


def test_bad_archive_hash_rejected(release, tmp_path):
    path, _ = archive(release, tmp_path)
    with pytest.raises(ValueError, match='checksum'):
        release.read_overlay(path, '0' * 64)


def test_duplicate_archive_names_rejected(release, tmp_path):
    path, checksum = archive(release, tmp_path, duplicate=True)
    with pytest.raises(ValueError, match='members'):
        release.read_overlay(path, checksum)


def test_secret_payload_rejected(release, tmp_path):
    path, checksum = archive(release, tmp_path, extra='deploy/.env')
    with pytest.raises(ValueError, match='invalid_payload'):
        release.read_overlay(path, checksum)


def test_concurrent_server_edit_not_overwritten(release, tmp_path):
    path, checksum = archive(release, tmp_path)
    target = release.OLD / min(release.RUNTIME)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'teammate edit')
    with pytest.raises(ValueError, match='server_file_conflict'):
        release.read_overlay(path, checksum)
    assert target.read_bytes() == b'teammate edit'
