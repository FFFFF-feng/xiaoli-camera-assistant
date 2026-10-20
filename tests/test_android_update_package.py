import importlib.util
import json
import re
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def packager():
    path = Path(__file__).resolve().parents[1] / 'scripts/package_android_update.py'
    spec = importlib.util.spec_from_file_location('android_update_packager', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def apk_fixture(tmp_path, *, data=b'current frontend', extra=None, server_url=None):
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_bytes(b'current frontend')
    apk = tmp_path / 'test.apk'
    config = {'appId': 'com.xiaoli.cameraassistant', 'server': {}}
    if server_url:
        config['server']['url'] = server_url
    with zipfile.ZipFile(apk, 'w') as archive:
        archive.writestr('assets/public/index.html', data)
        archive.writestr('assets/capacitor.config.json', json.dumps(config))
        if extra:
            archive.writestr(*extra)
    return apk, dist


def test_latest_frontend_allowed(packager, tmp_path):
    apk, dist = apk_fixture(tmp_path, extra=('assets/public/cordova.js', b''))
    assert packager.verify_assets(apk, dist, []) == 1


def test_old_frontend_rejected(packager, tmp_path):
    apk, dist = apk_fixture(tmp_path, data=b'old frontend')
    with pytest.raises(ValueError, match='resource_mismatch'):
        packager.verify_assets(apk, dist, [])


def test_old_hashed_assets_rejected(packager, tmp_path):
    apk, dist = apk_fixture(tmp_path, extra=('assets/public/assets/old.js', b'obsolete'))
    with pytest.raises(ValueError, match='stale_frontend'):
        packager.verify_assets(apk, dist, [])


@pytest.mark.parametrize('name', ['assets/.env', 'assets/knowledge.db', 'assets/signing.keystore'])
def test_private_files_rejected(packager, tmp_path, name):
    apk, dist = apk_fixture(tmp_path, extra=(name, b'private'))
    with pytest.raises(ValueError, match='private_file'):
        packager.verify_assets(apk, dist, [])


def test_secret_values_rejected_without_disclosing_value(packager, tmp_path, capsys):
    secret = b'fake-test-token-never-a-real-key'
    apk, dist = apk_fixture(tmp_path, extra=('assets/private.txt', secret))
    with pytest.raises(ValueError, match='private_value') as error:
        packager.verify_assets(apk, dist, [secret])
    assert secret.decode() not in str(error.value) + capsys.readouterr().out


def test_remote_webview_url_not_silently_bundled(packager, tmp_path):
    apk, dist = apk_fixture(tmp_path, server_url='https://example.com')
    with pytest.raises(ValueError, match='native_configuration'):
        packager.verify_assets(apk, dist, [])


def test_upgrade_requires_same_signature_and_increased_version(packager):
    old = {'package_name': 'com.xiaoli.cameraassistant', 'signer_sha256': 'same', 'version_code': 1}
    packager.verify_upgrade(old, {**old, 'version_code': 2})
    with pytest.raises(ValueError, match='not_increased'):
        packager.verify_upgrade(old, old)
    with pytest.raises(ValueError, match='certificate_changed'):
        packager.verify_upgrade(old, {**old, 'version_code': 2, 'signer_sha256': 'other'})
    with pytest.raises(ValueError, match='package_name_changed'):
        packager.verify_upgrade(old, {**old, 'version_code': 2, 'package_name': 'other'})


def test_private_configuration_collected_without_output(packager, tmp_path, capsys):
    secret = 'fake-private-token-for-scan-123456'
    (tmp_path / '.env').write_text('MOBILE_API_TOKEN=' + secret)
    assert secret.encode() in packager.private_values(tmp_path)
    assert not capsys.readouterr().out


def test_android_version_matches_frontend_and_lockfile():
    root = Path(__file__).resolve().parents[1]
    gradle = (root / 'mobile/android/app/build.gradle').read_text(encoding='utf-8')
    version = re.search(r'versionName "([^"]+)"', gradle)[1]
    assert int(re.search(r'versionCode (\d+)', gradle)[1]) > 1
    package = json.loads((root / 'mobile/package.json').read_text(encoding='utf-8'))
    lock = json.loads((root / 'mobile/package-lock.json').read_text(encoding='utf-8'))
    assert package['version'] == lock['version'] == lock['packages']['']['version'] == version
