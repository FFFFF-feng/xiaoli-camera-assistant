"""Apply the reviewed 2026-10-19 package on the existing ECS; never print secrets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.request import ProxyHandler, build_opener

OLD = Path('/opt/xiaoli-release-20261014/xiaoli')
ARCHIVE = Path('/opt/xiaoli-server-20261019.tar.gz')
SHA256 = '651c1b6a0d19d3ce326bb2d62d992f8bcf087cad3af9516c97740fd570ff3228'
STATUS = Path('/opt/xiaoli-update-20261019-status.json')
HTTP = build_opener(ProxyHandler({}))


def run(args, *, capture=False, timeout=1800):
    result = subprocess.run(args, check=True, text=True, timeout=timeout,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None


def inspect(name):
    return json.loads(run(['docker', 'inspect', name], capture=True))[0]


def compose(root):
    deploy = root / 'deploy'
    args = ['docker', 'compose', '--project-name', 'deploy', '--env-file', str(deploy / '.env')]
    for name in ('compose.yaml', 'compose.prebuilt.yaml', 'compose.ip.yaml'):
        args.extend(['-f', str(deploy / name)])
    return args


def verify_archive(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != SHA256:
        raise ValueError('release_checksum_mismatch')
    with tarfile.open(path, 'r:gz') as package:
        members = package.getmembers()
        if not 1 <= len(members) <= 2000 or sum(m.size for m in members) > 256 * 1024 * 1024:
            raise ValueError('release_size_invalid')
        for member in members:
            parts = PurePosixPath(member.name)
            if (not member.isfile() or parts.is_absolute() or '..' in parts.parts
                    or len(parts.parts) < 2 or parts.parts[0] != 'xiaoli'
                    or member.size > 64 * 1024 * 1024
                    or (parts.name.startswith('.env') and parts.name != '.env.example')):
                raise ValueError('release_member_invalid')


def extract_release(destination):
    destination.mkdir(mode=0o755)
    with tarfile.open(ARCHIVE, 'r:gz') as package:
        for member in package.getmembers():
            path = destination.joinpath(*PurePosixPath(member.name).parts)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            source = package.extractfile(member)
            if source is None:
                raise ValueError('release_member_unreadable')
            with source, path.open('xb') as target:
                shutil.copyfileobj(source, target)
            path.chmod(0o644)


def wait_healthy():
    for _ in range(90):
        try:
            with HTTP.open('http://127.0.0.1:8080/health', timeout=3) as response:
                data = json.load(response)
            if data.get('status') == 'ok' and data.get('service') == 'xiaoli-mobile-api':
                return data
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError('new_service_health_timeout')


def static_check(root):
    with HTTP.open('http://127.0.0.1:8080/', timeout=10) as response:
        page = response.read()
    if page != (root / 'mobile/dist/index.html').read_bytes():
        raise RuntimeError('frontend_build_mismatch')
    assets = re.findall(rb'(?:src|href)="(/assets/[^"?#]+)', page)
    if len(assets) < 2:
        raise RuntimeError('frontend_assets_missing')
    for asset in assets:
        name = asset.decode()
        with HTTP.open('http://127.0.0.1:8080' + name, timeout=20) as response:
            actual = response.read()
        if actual != (root / 'mobile/dist' / name.lstrip('/')).read_bytes():
            raise RuntimeError('static_asset_transfer_mismatch')
    return len(assets)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('requires_server_root')
    verify_archive(ARCHIVE)
    old_app, old_caddy = inspect('deploy-app-1'), inspect('deploy-caddy-1')
    if old_app['Config']['Labels'].get('com.docker.compose.project') != 'deploy':
        raise RuntimeError('unexpected_compose_project')
    if Path(old_app['Config']['Labels']['com.docker.compose.project.working_dir']) != OLD / 'deploy':
        raise RuntimeError('unexpected_production_directory')
    mounts = [m for m in old_app['Mounts'] if m['Destination'] == '/app/data']
    if len(mounts) != 1 or mounts[0].get('Name') != 'deploy_xiaoli-data':
        raise RuntimeError('unexpected_production_data_volume')
    config = OLD / 'deploy/.env'
    original_hash = hashlib.sha256(config.read_bytes()).hexdigest()
    environment = dict(value.split('=', 1) for value in old_app['Config']['Env'])
    mobile_token = environment.get('MOBILE_API_TOKEN', '')
    token_source = 'existing_mobile_token'
    if len(mobile_token) < 24:
        # Same analysis privilege, not an administrator credential; no new secret is generated.
        mobile_token = environment.get('WEB_ACCESS_CODE', '')
        token_source = 'existing_experience_code'
    native_ready = re.fullmatch(r'[A-Za-z0-9._~-]{24,}', mobile_token) is not None
    print(json.dumps({'preflight': 'passed', 'native_token_available': native_ready}), flush=True)
    if not args.apply:
        return

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')  # noqa: UP017 - server Python 3.10
    backup = Path('/opt') / ('xiaoli-backup-' + stamp)
    backup.mkdir(mode=0o700)
    shutil.copytree(OLD, backup / 'xiaoli')
    (backup / 'xiaoli/deploy/.env').chmod(0o600)
    database = Path(mounts[0]['Source']) / 'knowledge.db'
    if database.exists():
        with (
            sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as source,
            sqlite3.connect(backup / 'knowledge.db') as target,
        ):
            source.backup(target)
        (backup / 'knowledge.db').chmod(0o600)
    rollback_image = 'xiaoli-app:rollback-' + stamp.lower()
    run(['docker', 'tag', old_app['Image'], rollback_image])
    release = Path('/opt') / ('xiaoli-release-' + stamp)
    extract_release(release)
    root = release / 'xiaoli'
    private = root / 'deploy/.env'
    shutil.copy2(config, private)
    private.chmod(0o600)
    additions = '\n# Retain the currently deployed Caddy image.\nXIAOLI_CADDY_IMAGE=' + old_caddy['Config']['Image'] + '\n'
    if native_ready:
        additions += 'MOBILE_API_TOKEN=' + mobile_token + '\n'
    with private.open('a', encoding='utf-8') as stream:
        stream.write(additions)
    STATUS.write_text(json.dumps({'phase': 'backup_complete', 'backup': str(backup),
                                 'release': str(root)}, indent=2), encoding='utf-8')
    print('BACKUP_COMPLETE ' + str(backup), flush=True)
    command = compose(root)
    run(command + ['config', '--quiet'])
    with (backup / 'build.log').open('w') as log:
        subprocess.run(command + ['build', 'app'], check=True, stdout=log,
                       stderr=subprocess.STDOUT, timeout=1800)
    print('IMAGE_BUILD_COMPLETE', flush=True)
    run(['docker', 'run', '--rm', '--network', 'none', '--env-file', str(private),
         '--entrypoint', 'python', 'deploy-app', '-c',
         'from camera_assistant.web_app import from_env; from_env(); print("image_startup_ok")'])
    run(['docker', 'run', '--rm', '--network', 'deploy_default',
         '--entrypoint', 'caddy', '-e', 'XIAOLI_IP=115.29.241.181',
         '-v', str(root / 'deploy/Caddyfile.ip') + ':/etc/caddy/Caddyfile:ro',
         old_caddy['Image'], 'validate', '--config', '/etc/caddy/Caddyfile', '--adapter', 'caddyfile'])
    try:
        run(command + ['up', '-d', '--no-build', 'app', 'caddy'])
        health = wait_healthy()
        new_app = inspect('deploy-app-1')
        if new_app['Image'] == old_app['Image']:
            raise RuntimeError('old_image_still_running')
        new_mounts = [m for m in new_app['Mounts'] if m['Destination'] == '/app/data']
        if len(new_mounts) != 1 or new_mounts[0].get('Name') != 'deploy_xiaoli-data':
            raise RuntimeError('data_volume_changed')
        count = static_check(root)
        with HTTP.open('https://115.29.241.181/health', timeout=20) as response:
            if json.load(response).get('status') != 'ok':
                raise RuntimeError('public_https_check_failed')
        with HTTP.open('https://115.29.241.181/web-config', timeout=20) as response:
            web_config = json.load(response)
        if web_config.get('invite_required') or web_config.get('knowledge_workbench_url'):
            raise RuntimeError('unexpected_public_interface')
        if native_ready:
            code = ('import os,json,urllib.request; '
                    'r=urllib.request.Request("http://127.0.0.1:8080/api/v1/devices",'
                    'headers={"Origin":"http://localhost","Authorization":"Bearer "+os.environ["MOBILE_API_TOKEN"]}); '
                    'd=json.load(urllib.request.urlopen(r,timeout=20)); '
                    'print(json.dumps({"cameras":len(d["cameras"]),"phones":len(d["phones"])}))')
            native_result = json.loads(run(['docker', 'exec', 'deploy-app-1', 'python', '-c', code], capture=True))
        else:
            native_result = {'requires_private_configuration': True}
        if hashlib.sha256(config.read_bytes()).hexdigest() != original_hash:
            raise RuntimeError('original_private_configuration_changed')
        result = {'phase': 'completed', 'url': 'https://115.29.241.181/',
                  'backup': str(backup), 'release': str(root), 'image': new_app['Image'],
                  'analysis_mode': health['analysis_mode'], 'static_assets_verified': count,
                  'data_volume_preserved': True, 'original_private_config_preserved': True,
                  'native_ready': native_ready, 'native_token_source': token_source if native_ready else None,
                  'native_catalog_check': native_result, 'knowledge_admin_public': False,
                  'real_photo_analysis_tested': False}
        STATUS.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
    except Exception:
        run(['docker', 'tag', rollback_image, 'deploy-app'])
        run(compose(OLD) + ['up', '-d', '--no-build', '--force-recreate', 'app', 'caddy'])
        STATUS.write_text(json.dumps({'phase': 'rolled_back', 'backup': str(backup)}), encoding='utf-8')
        raise


if __name__ == '__main__':
    main()
