"""Interactive ECS native-client setup. The human enters and confirms the token.

No secret in command arguments, receipts, APKs, public files or terminal output.
Only the existing app is recreated; HTTPS, volumes and web sessions are retained.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ORIGIN = 'https://115.29.241.181'
ROOT = Path('/opt/xiaoli-devices-20261020T024905Z/xiaoli')
TOKEN_PATTERN = re.compile(r'[A-Za-z0-9._~-]{24,512}')


def command(args, timeout=120):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=timeout).strip()


def inspect(name):
    return json.loads(command(['docker', 'inspect', name]))[0]


def environment(container):
    return dict(value.split('=', 1) for value in container['Config']['Env'])


def replace_mobile_token(content, token):
    if not TOKEN_PATTERN.fullmatch(token):
        raise ValueError('invalid_mobile_token')
    lines = content.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines)
               if re.match(r'^\s*(?:export\s+)?MOBILE_API_TOKEN\s*=', line)]
    # Do not attempt to reinterpret an unusual multiline secret assignment.
    for index in matches:
        value = lines[index].split('=', 1)[1].strip()
        if value.startswith(('"', "'")) and (len(value) < 2 or value[-1] != value[0]):
            raise ValueError('multiline_mobile_assignment_requires_manual_review')
    result = ''.join(line for i, line in enumerate(lines) if i not in matches)
    if result and not result.endswith('\n'):
        result += '\n'
    return result + 'MOBILE_API_TOKEN=' + token + '\n'


def compose(container):
    labels = container['Config']['Labels']
    if (labels.get('com.docker.compose.project') != 'deploy'
            or labels.get('com.docker.compose.project.working_dir') != str(ROOT / 'deploy')):
        raise ValueError('unexpected_compose_identity')
    args = ['docker', 'compose', '--project-name', 'deploy', '--env-file', str(ROOT / 'deploy/.env')]
    for name in labels['com.docker.compose.project.config_files'].split(','):
        if Path(name).parent != ROOT / 'deploy' or not Path(name).is_file():
            raise ValueError('unexpected_compose_configuration')
        args.extend(['-f', name])
    return args


def query(path, *, token=None, method='GET', headers=None):
    supplied = {'Origin': 'http://localhost', **(headers or {})}
    if token is not None:
        supplied['Authorization'] = 'Bearer ' + token
    request = Request(ORIGIN + path, headers=supplied, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, response.headers, response.read()
    except HTTPError as error:
        return error.code, error.headers, b''


def verify_public(token):
    code, _, body = query('/health')
    if code != 200 or json.loads(body).get('analysis_mode') != 'cloud':
        raise ValueError('public_health_failed')
    code, headers, body = query('/api/v1/devices', token=token)
    if code != 200 or headers.get('Access-Control-Allow-Origin') != 'http://localhost':
        raise ValueError('public_native_auth_failed')
    data = json.loads(body)
    for invalid in (None, 'not-a-valid-mobile-token'):
        if query('/api/v1/devices', token=invalid)[0] != 401:
            raise ValueError('native_auth_guard_failed')
    code, headers, _ = query('/api/v1/analyze-scene', method='OPTIONS', headers={
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'authorization,content-type',
    })
    if code not in (200, 204) or headers.get('Access-Control-Allow-Origin') != 'http://localhost':
        raise ValueError('native_upload_preflight_failed')
    return {'https_verified': True, 'native_authenticated': True, 'unauthorized_rejected': True,
            'upload_cors_verified': True, 'phones_including_generic': len(data['phones']),
            'lens_references': len(data['lens_references']), 'cloud_model_calls': 0}


def save_private(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    app, caddy = inspect('deploy-app-1'), inspect('deploy-caddy-1')
    original = environment(app)
    commands = compose(app)
    mounts = [m for m in app['Mounts'] if m['Destination'] == '/app/data']
    if (original.get('WEB_ORIGIN') != ORIGIN or original.get('KNOWLEDGE_RETRIEVAL_MODE') != 'managed'
            or len(mounts) != 1 or mounts[0].get('Name') != 'deploy_xiaoli-data'):
        raise ValueError('unexpected_service_configuration')
    private = ROOT / 'deploy/.env'
    before = private.read_bytes()
    print('PREFLIGHT_OK; HTTPS endpoint: ' + ORIGIN, flush=True)
    print('Existing native token configured: ' + str(bool(original.get('MOBILE_API_TOKEN'))), flush=True)
    if not args.apply:
        return
    if original.get('MOBILE_API_TOKEN'):
        print('Replacing the existing token will disconnect apps still using that token.', flush=True)
    print('Human action: paste the token from local mobile-access.json; input is hidden.', flush=True)
    token = getpass.getpass('Mobile token (hidden): ')
    updated = replace_mobile_token(before.decode('utf-8'), token).encode('utf-8')
    print('This enables token-authenticated app analysis on the existing server; cloud usage may incur fees.', flush=True)
    if input('Type ENABLE to apply, or anything else to cancel: ').strip() != 'ENABLE':
        print('CANCELLED; no configuration changed.', flush=True)
        return
    if private.read_bytes() != before or inspect('deploy-app-1')['Id'] != app['Id']:
        raise ValueError('service_changed_while_waiting')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')  # noqa: UP017 -- ECS Python 3.10
    backup = Path('/opt') / ('xiaoli-mobile-setup-' + stamp)
    backup.mkdir(mode=0o700)
    save_private(backup / 'previous.env', before)
    status = {'state': 'prepared', 'origin': ORIGIN, 'root': str(ROOT),
              'backup': str(backup), 'credentials_in_receipt': False}
    receipt = backup / 'status.json'
    receipt.write_text(json.dumps(status, indent=2))
    pending = ROOT / 'deploy' / ('.env.mobile-' + stamp)
    save_private(pending, updated)
    os.replace(pending, private)
    restart = commands + ['up', '-d', '--no-build', '--no-deps', '--force-recreate', 'app']
    try:
        command(commands + ['config', '--quiet'])
        command(restart)
        for attempt in range(30):
            try:
                checks = verify_public(token)
                break
            except (OSError, ValueError):
                if attempt == 29:
                    raise
                time.sleep(2)
        current = inspect('deploy-app-1')
        now = environment(current)
        if (current['Image'] != app['Image'] or inspect('deploy-caddy-1')['Id'] != caddy['Id']
                or {k: v for k, v in now.items() if k != 'MOBILE_API_TOKEN'}
                != {k: v for k, v in original.items() if k != 'MOBILE_API_TOKEN'}
                or now.get('MOBILE_API_TOKEN') != token):
            raise ValueError('unexpected_configuration_change')
        database = Path(mounts[0]['Source']) / 'knowledge.db'
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
            published = connection.execute("SELECT count(*) FROM revisions WHERE status='published'").fetchone()[0]
        status.update(state='success', published_knowledge=published, **checks)
        receipt.write_text(json.dumps(status, indent=2))
        print('MOBILE_PUBLIC_READY ' + str(receipt), flush=True)
        print(json.dumps(checks), flush=True)
    except BaseException:
        rollback = ROOT / 'deploy' / ('.env.mobile-rollback-' + stamp)
        save_private(rollback, before)
        os.replace(rollback, private)
        command(restart)
        status['state'] = 'rolled_back'
        receipt.write_text(json.dumps(status, indent=2))
        raise


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        # Do not echo HTTP headers, environment values or subprocess stderr.
        print('SETUP_FAILED (' + type(error).__name__ + '); retain old config or inspect private receipt.', flush=True)
        raise SystemExit(1) from None
