"""Verify and deliver an APK update; never bundle credentials or backend data."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def private_values(root):
    values = set()
    for key, value in os.environ.items():
        if len(value) >= 16 and re.search('KEY|TOKEN|SECRET|PASSWORD', key, re.IGNORECASE):
            values.add(value.encode())
    for folder in (root, root / 'deploy'):
        for path in folder.glob('.env*'):
            if not path.is_file() or path.name.endswith('.example'):
                continue
            for key, value in dotenv_values(path).items():
                if value and len(value) >= 16 and re.search('KEY|TOKEN|SECRET|PASSWORD', key, re.IGNORECASE):
                    values.add(value.encode())
    token = root / '.launcher/mobile-access.json'
    if token.is_file():
        value = json.loads(token.read_text(encoding='utf-8')).get('token')
        if isinstance(value, str) and value:
            values.add(value.encode())
    return values


def verify_assets(apk, dist, secrets):
    expected = {p.relative_to(dist).as_posix(): p.read_bytes()
                for p in dist.rglob('*') if p.is_file()}
    if 'index.html' not in expected:
        raise ValueError('frontend_build_missing')
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate_apk_entry')
        for name in names:
            leaf = Path(name).name.lower()
            if leaf.startswith('.env') or leaf.endswith(('.key', '.pem', '.jks', '.keystore', '.db', '.sqlite', '.sqlite3')):
                raise ValueError('private_file_in_apk')
            if any(value in archive.read(name) for value in secrets):
                raise ValueError('private_value_in_apk')
        bundled = {name.removeprefix('assets/public/') for name in names
                   if name.startswith('assets/public/') and not name.endswith('/')}
        # Capacitor generates these bridge files; all other files must match dist.
        if bundled - set(expected) - {'cordova.js', 'cordova_plugins.js'}:
            raise ValueError('stale_frontend_asset')
        for name, data in expected.items():
            if archive.read('assets/public/' + name) != data:
                raise ValueError('frontend_resource_mismatch')
        config = json.loads(archive.read('assets/capacitor.config.json'))
        if config.get('appId') != 'com.xiaoli.cameraassistant' or config.get('server', {}).get('url'):
            raise ValueError('unexpected_native_configuration')
    return len(expected)


def metadata(apk, tools, env):
    badging = subprocess.check_output([str(tools / 'aapt.exe'), 'dump', 'badging', str(apk)],
                                      text=True, encoding='utf-8', env=env)
    package = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging)
    minimum = re.search(r"sdkVersion:'(\d+)'", badging)
    target = re.search(r"targetSdkVersion:'(\d+)'", badging)
    if not package or not minimum or not target:
        raise ValueError('apk_metadata_unreadable')
    signing = subprocess.check_output([str(tools / 'apksigner.bat'), 'verify', '--print-certs', str(apk)],
                                      text=True, encoding='utf-8', env=env)
    certificates = re.findall(r'Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)', signing)
    if len(certificates) != 1:
        raise ValueError('unexpected_signer_set')
    return {'package_name': package[1], 'version_code': int(package[2]), 'version_name': package[3],
            'min_android_api': int(minimum[1]), 'target_android_api': int(target[1]),
            'signer_sha256': certificates[0].lower()}


def verify_upgrade(previous, current):
    if previous['package_name'] != current['package_name']:
        raise ValueError('package_name_changed')
    if previous['signer_sha256'] != current['signer_sha256']:
        raise ValueError('signing_certificate_changed_do_not_uninstall')
    if current['version_code'] <= previous['version_code']:
        raise ValueError('version_code_not_increased')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', default='20261020')
    args = parser.parse_args()
    if not re.fullmatch(r'\d{8}', args.date):
        raise ValueError('invalid_release_date')
    apk = ROOT / 'output/mobile/xiaoli-camera-assistant-debug.apk'
    previous = ROOT / 'output/releases/xiaoli-android-20261019/xiaoli-camera-assistant-20261019-debug.apk'
    tools = ROOT / '.android-tools/sdk/build-tools/36.0.0'
    java = next((ROOT / '.android-tools/jdk').glob('*/bin/java.exe'))
    env = dict(os.environ, JAVA_HOME=str(java.parent.parent))
    old, current = metadata(previous, tools, env), metadata(apk, tools, env)
    verify_upgrade(old, current)
    count = verify_assets(apk, ROOT / 'mobile/dist', private_values(ROOT))
    out = ROOT / 'output/releases' / ('xiaoli-android-' + args.date)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"xiaoli-camera-assistant-{args.date}-v{current['version_name']}-debug.apk"
    shutil.copyfile(apk, target)
    notes = ROOT / 'docs/android-update-20261020.txt'
    shutil.copyfile(notes, out / '安装与更新说明.txt')
    manifest = {**current, 'debug_signed': True, 'created_at_local': datetime.now().astimezone().isoformat(),
                'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'includes_working_tree_changes': True, 'previous_version': old['version_name'],
                'same_signer_as_previous_apk': True, 'bundled_frontend_files_verified': count,
                'private_values_absent': True, 'device_install_test': 'not_performed',
                'server_configuration_changed_this_build': False, 'connection_mode': 'manual_url_and_token',
                'files': {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                          for p in (target, out / '安装与更新说明.txt')}}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'SHA256SUMS.txt').write_text('\n'.join(
        hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name
        for p in (target, out / '安装与更新说明.txt', out / 'manifest.json')) + '\n', encoding='utf-8')
    print(json.dumps({'apk': str(target), 'version': current['version_name'],
                      'version_code': current['version_code'], 'same_signer': True,
                      'frontend_files_verified': count, 'private_values_absent': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
