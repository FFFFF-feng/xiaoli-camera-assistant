"""Deploy the reviewed device overlay, retaining secrets, data and rollback image.

Run on the existing ECS with an explicitly supplied archive checksum.
Python 3.10 compatible. No package downloads or database replacement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.request import ProxyHandler, build_opener

OLD = Path('/opt/xiaoli-release-20261019T122258Z/xiaoli')
EXPECTED_IMAGE = 'sha256:d5de693b479867a5160177db47fa5b44d59c2bcfb345d3258fae384937ebe753'
VOLUME = 'deploy_xiaoli-data'
RUNTIME = {
    'src/camera_assistant/models.py', 'src/camera_assistant/pipeline.py',
    'src/camera_assistant/mobile_api.py', 'src/camera_assistant/knowledge/context.py',
    'src/camera_assistant/services/phone_knowledge.py',
    'src/camera_assistant/services/device_reference_catalog.py',
    'src/camera_assistant/services/device_optics.py', 'scripts/verify_managed_retrieval.py',
}
SOURCES = {'README.md', '启动项目.cmd', 'scripts/launch_apps.py', 'scripts/launch_web.py',
           'mobile/src/App.vue', 'mobile/src/types.ts', 'mobile/src/device-selection.mjs',
           'mobile/src/components/DevicePicker.vue'}
HTTP = build_opener(ProxyHandler({}))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(args, timeout=600):
    return subprocess.check_output(args, text=True, timeout=timeout).strip()


def inspect(name):
    return json.loads(run(['docker', 'inspect', name]))[0]


def allowed(name):
    path = PurePosixPath(name)
    return (not path.is_absolute() and '..' not in path.parts and '\\' not in name
            and (name in RUNTIME | SOURCES or name == 'mobile/dist/index.html'
                 or (name.startswith('mobile/dist/assets/') and len(path.parts) == 4
                     and path.suffix in {'.js', '.css', '.webp'})))


def read_overlay(archive, checksum):
    if digest(archive.read_bytes()) != checksum:
        raise ValueError('archive_checksum_mismatch')
    with tarfile.open(archive) as package:
        members = package.getmembers()
        if (len(members) > 100 or sum(m.size for m in members) > 16 * 1024**2
                or any(not m.isfile() for m in members)
                or len({m.name for m in members}) != len(members)):
            raise ValueError('invalid_archive_members')
        files = {m.name: package.extractfile(m).read() for m in members}
    manifest = json.loads(files.pop('manifest.json'))
    if manifest.get('schema') != 1 or manifest.get('release') != 'device-options-20261020':
        raise ValueError('invalid_manifest')
    if files.keys() != manifest['files'].keys() or not RUNTIME <= files.keys():
        raise ValueError('unexpected_file_set')
    for name, data in files.items():
        entry = manifest['files'][name]
        if not allowed(name) or digest(data) != entry['after'] or len(data) != entry['size']:
            raise ValueError('invalid_payload:' + name)
        target = OLD / name
        existing = digest(target.read_bytes()) if target.is_file() else None
        if existing not in (entry['before'], entry['after']):
            raise ValueError('server_file_conflict:' + name)
    return manifest, files


def compose(root, names):
    args = ['docker', 'compose', '--project-name', 'deploy', '--env-file', str(root / 'deploy/.env')]
    for name in names:
        args += ['-f', str(root / 'deploy' / name)]
    return args


def health():
    with HTTP.open('http://127.0.0.1:8080/health', timeout=10) as response:
        result = json.load(response)
    if result.get('status') != 'ok' or result.get('analysis_mode') != 'cloud':
        raise ValueError('unexpected_health')
    return result


SMOKE = '''
import json,sqlite3,runpy
from dataclasses import replace
from pathlib import Path
from fastapi.testclient import TestClient
from camera_assistant.config import Settings
from camera_assistant.pipeline import CameraAssistantPipeline
from camera_assistant.mobile_api import create_app
s=Settings.from_env()
assert s.knowledge_mode=='managed' and str(s.knowledge_db_path)=='/app/data/knowledge.db'
p=CameraAssistantPipeline(replace(s,demo_mode=True,api_key='',detector_enabled=False))
c=TestClient(create_app(s,'deployment-device-probe-not-a-secret',p))
r=c.get('/api/v1/devices',headers={'Authorization':'Bearer deployment-device-probe-not-a-secret'})
assert r.status_code==200
d=r.json()
assert len(d['phones'])>=514 and len(d['lens_references'])>=1638
phone=next(x for x in d['phones'] if x['model']=='HONOR 400 Pro')
assert len(phone['lenses'])>=3 and any(x.get('aperture')==2.4 for x in phone['lenses'])
lens=next(x for x in d['lens_references'] if x['brand']=='Sony' and 'E 18-55mm f/3.5-5.6 OSS' in x['display_name'])
assert (lens['focal_min_mm'],lens['focal_max_mm'],lens['max_aperture_wide'],lens['max_aperture_tele'])==(18,55,3.5,5.6)
v=runpy.run_path('/app/scripts/verify_managed_retrieval.py')['verify'](Path('/app/data/knowledge.db'),require_managed_env=True)
with sqlite3.connect('/app/data/knowledge.db') as db:
 n=db.execute("SELECT count(*) FROM revisions WHERE status='published'").fetchone()[0]
print('DEVICE_SMOKE='+json.dumps({'phones':len(d['phones']),'lens_references':len(d['lens_references']),'published':n,'mode':s.knowledge_mode,'cloud_calls':0}))
'''


def deploy(archive, checksum):
    manifest, files = read_overlay(archive, checksum)
    app, caddy = inspect('deploy-app-1'), inspect('deploy-caddy-1')
    labels = app['Config']['Labels']
    if (app['Image'] != EXPECTED_IMAGE or labels['com.docker.compose.project'] != 'deploy'
            or labels['com.docker.compose.project.working_dir'] != str(OLD / 'deploy')):
        raise ValueError('unexpected_production_identity')
    if not any(m.get('Name') == VOLUME and m['Destination'] == '/app/data' for m in app['Mounts']):
        raise ValueError('unexpected_data_mount')
    env = dict(item.split('=', 1) for item in app['Config']['Env'])
    if env.get('KNOWLEDGE_RETRIEVAL_MODE') != 'managed':
        raise ValueError('production_not_managed')
    config_files = labels['com.docker.compose.project.config_files'].split(',')
    if any(Path(p).parent != OLD / 'deploy' for p in config_files):
        raise ValueError('unexpected_compose_location')
    names = [Path(p).name for p in config_files]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')  # noqa: UP017 -- ECS Python 3.10
    release = Path('/opt') / ('xiaoli-devices-' + stamp)
    release.mkdir(mode=0o700)
    original_env_hash = digest((OLD / 'deploy/.env').read_bytes())
    mountpoint = Path(inspect(VOLUME)['Mountpoint'])
    with sqlite3.connect(mountpoint / 'knowledge.db') as source:
        before = source.execute("SELECT count(*) FROM revisions WHERE status='published'").fetchone()[0]
        with sqlite3.connect(release / 'before-knowledge.db') as backup:
            source.backup(backup)
    (release / 'before-knowledge.db').chmod(0o600)
    new = release / 'xiaoli'
    shutil.copytree(OLD, new, symlinks=True, ignore=shutil.ignore_patterns(
        '.git', 'node_modules', '.venv', '__pycache__', 'output', '.launcher'))
    stage = release / 'overlay'
    stage.mkdir()
    for name, data in files.items():
        for base in (new, stage):
            path = base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink():
                raise ValueError('refuse_symlink_target')
            path.write_bytes(data)
            path.chmod(0o644)
    dockerfile = 'ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\n'
    for name in sorted(RUNTIME):
        dockerfile += f'COPY {name} /app/{name}\n'
    dockerfile += 'COPY mobile/dist/ /app/mobile/dist/\n'
    (stage / 'Dockerfile').write_text(dockerfile)
    image = 'xiaoli-device-options:' + stamp.lower()
    run(['docker', 'build', '--network=none', '--pull=false', '--build-arg',
         'BASE_IMAGE=' + app['Image'], '-t', image, str(stage)])
    override = 'compose.device-options.yaml'
    (new / 'deploy' / override).write_text('services:\n  app:\n    image: ' + image + '\n')
    if digest((new / 'deploy/.env').read_bytes()) != original_env_hash:
        raise ValueError('private_config_changed')
    rollback = compose(OLD, names) + ['up', '-d', '--no-deps', '--no-build', '--force-recreate', 'app']
    status = {'release': str(new), 'old_root': str(OLD), 'old_image': app['Image'],
              'new_image': image, 'published_before': before, 'rollback_command': rollback,
              'archive_sha256': checksum, 'state': 'prepared'}
    status_file = release / 'status.json'
    status_file.write_text(json.dumps(status, indent=2))
    try:
        run(compose(new, names + [override]) + ['up', '-d', '--no-deps', '--no-build', '--force-recreate', 'app'])
        ready = False
        for _ in range(40):
            try:
                health()
                ready = True
                break
            except (OSError, ValueError):
                time.sleep(2)
        if not ready:
            raise ValueError('startup_timeout')
        current = inspect('deploy-app-1')
        if (set(current['Config']['Env']) != set(app['Config']['Env'])
                or not current['HostConfig']['ReadonlyRootfs']
                or current['Config']['User'] != app['Config']['User']
                or inspect('deploy-caddy-1')['Id'] != caddy['Id']):
            raise ValueError('deployment_invariant_changed')
        smoke = subprocess.run(['docker', 'exec', '-i', 'deploy-app-1', 'python', '-'],
                               input=SMOKE, text=True, capture_output=True, timeout=240, check=False)
        (release / 'smoke.log').write_text(smoke.stdout + smoke.stderr)
        if smoke.returncode != 0:
            raise ValueError('offline_smoke_failed_see_private_log')
        with sqlite3.connect(mountpoint / 'knowledge.db') as db:
            after = db.execute("SELECT count(*) FROM revisions WHERE status='published'").fetchone()[0]
        if after < before:
            raise ValueError('published_knowledge_decreased')
        for name, entry in manifest['files'].items():
            if name.startswith('mobile/dist/'):
                url = 'http://127.0.0.1:8080/' + ('' if name == 'mobile/dist/index.html' else name.removeprefix('mobile/dist/'))
                with HTTP.open(url, timeout=15) as response:
                    if digest(response.read()) != entry['after']:
                        raise ValueError('served_asset_mismatch:' + name)
        status.update(state='success', published_after=after,
                      caddy_unchanged=True, private_config_unchanged=True)
        print(smoke.stdout, flush=True)
        print('DEPLOYMENT_SUCCESS ' + str(new), flush=True)
    except BaseException:
        run(rollback)
        status['state'] = 'rolled_back'
        status_file.write_text(json.dumps(status, indent=2))
        raise
    status_file.write_text(json.dumps(status, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply:
        deploy(args.archive, args.sha256)
    else:
        manifest, _ = read_overlay(args.archive, args.sha256)
        print('PREFLIGHT_OK files=' + str(len(manifest['files'])))
