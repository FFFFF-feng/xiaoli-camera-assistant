"""在已确认的生产实例批量启用检索；只变更知识模式，保留镜像、密钥、Caddy。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path('/opt/xiaoli-release-20261019T122258Z/xiaoli')
SCRIPTS = Path('/opt/xiaoli-knowledge-enable-20261020')
STATUS = SCRIPTS / 'status.json'
HTTP = build_opener(ProxyHandler({}))


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, timeout=1800, **kwargs)


def inspect(name):
    return json.loads(run(['docker', 'inspect', name], capture_output=True).stdout)[0]


def status(stage, **extra):
    STATUS.write_text(json.dumps({'stage': stage, **extra}, indent=2))
    print(stage, flush=True)


def compose():
    args = ['docker', 'compose', '--project-name', 'deploy', '--env-file', str(ROOT/'deploy/.env')]
    for file in ('compose.yaml', 'compose.prebuilt.yaml', 'compose.ip.yaml'):
        args.extend(['-f', str(ROOT/'deploy'/file)])
    return args


def healthy():
    for _ in range(90):
        try:
            with HTTP.open('http://127.0.0.1:8080/health', timeout=3) as response:
                result = json.load(response)
            if result.get('status') == 'ok':
                return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError('health_timeout')


def main():
    before = inspect('deploy-app-1')
    caddy = inspect('deploy-caddy-1')['Id']
    labels = before['Config']['Labels']
    if labels.get('com.docker.compose.project') != 'deploy':
        raise ValueError('wrong_compose_project')
    if Path(labels.get('com.docker.compose.project.working_dir', '')).resolve() != (ROOT/'deploy').resolve():
        raise ValueError('unexpected_working_dir')
    if not any(m.get('Name') == 'deploy_xiaoli-data' and m['Destination'] == '/app/data' for m in before['Mounts']):
        raise ValueError('unexpected_data_volume')
    image = before['Image']
    if inspect('deploy-app')['Id'] != image:
        raise ValueError('image_tag_changed')
    backup = SCRIPTS / ('backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))  # noqa: UP017 - Ubuntu host Python 3.10
    backup.mkdir(mode=0o700)
    env = ROOT/'deploy/.env'
    shutil.copy2(env, backup/'.env')
    (backup/'.env').chmod(0o600)
    status('publishing')
    output = '/app/data/knowledge-import-20261019/bulk-enabled-20261020'
    run(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--user', '10001:10001',
         '--security-opt', 'no-new-privileges:true', '--cap-drop', 'ALL', '--memory', '512m',
         '--cpus', '1', '--tmpfs', '/tmp:size=32m,mode=1777',
         '--mount', 'type=volume,src=deploy_xiaoli-data,dst=/app/data',
         '--mount', f'type=bind,src={SCRIPTS}/enable_repository_retrieval.py,dst=/release.py,readonly',
         image, 'python', '/release.py', '--db', '/app/data/knowledge.db', '--output', output,
         '--actor', '用户确认批量启用（20261019会话）', '--confirm-enable-all-reference'])
    # 切换前在原镜像隔离验证，避免启动空库或无命中的新服务。
    smoke = (SCRIPTS/'verify_managed_retrieval.py').read_text()
    run(['docker', 'exec', '-i', 'deploy-app-1', 'python', '-', '--db', '/app/data/knowledge.db'], input=smoke)
    status('switching')
    original = env.read_bytes()
    updated = original
    for key, value in ((b'KNOWLEDGE_RETRIEVAL_MODE', b'managed'),
                       (b'KNOWLEDGE_DB_PATH', b'/app/data/knowledge.db')):
        pattern = rb'(?m)^[ \t]*' + key + rb'[ \t]*=[^\r\n]*'
        line = key + b'=' + value
        if re.search(pattern, updated):
            updated = re.sub(pattern, lambda _, replacement=line: replacement, updated)
        else:
            updated = updated.rstrip(b'\r\n') + b'\n' + line + b'\n'
    try:
        env.write_bytes(updated)
        env.chmod(0o600)
        run(compose() + ['up', '-d', '--no-build', '--no-deps', '--force-recreate', 'app'])
        healthy()
        after = inspect('deploy-app-1')
        if after['Image'] != image or inspect('deploy-caddy-1')['Id'] != caddy:
            raise ValueError('unintended_container_change')
        ignored = {'KNOWLEDGE_RETRIEVAL_MODE', 'KNOWLEDGE_DB_PATH'}
        def preserved(container):
            return {v for v in container['Config']['Env'] if v.split('=', 1)[0] not in ignored}
        if preserved(before) != preserved(after):
            raise ValueError('unintended_environment_change')
        run(['docker', 'exec', '-i', 'deploy-app-1', 'python', '-', '--db', '/app/data/knowledge.db',
             '--require-managed-env'], input=smoke)
        status('complete', mode='managed', data_volume='deploy_xiaoli-data', caddy_unchanged=True,
               backup=str(backup), published_report=output+'/result.json')
    except BaseException:
        env.write_bytes(original)
        env.chmod(0o600)
        run(compose() + ['up', '-d', '--no-build', '--no-deps', '--force-recreate', 'app'])
        healthy()
        status('rolled_back', backup=str(backup))
        raise


if __name__ == '__main__':
    os.umask(0o077)
    main()
