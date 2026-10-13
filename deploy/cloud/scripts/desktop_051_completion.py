"""Read-only exact completed checkpoint check; no credentials printed."""
import argparse
import json
import re
import subprocess
from pathlib import Path


def validate(receipt, commit, sha256, api, worker, database):
    if (receipt.get('phase') != 'completed' or receipt.get('source_commit') != commit or
            receipt.get('source_sha256') != sha256 or
            receipt.get('target_schema') != '20261012_physical_membership' or
            not receipt.get('origin', {}).get('hashes') or
            not re.fullmatch(r'sha256:[a-f0-9]{64}', receipt.get('image_id', ''))):
        raise RuntimeError('Exact completed source/schema/origin evidence required')
    for container in (api, worker):
        if (container['Image'] != receipt['image_id'] or not container['State']['Running'] or
                container['State'].get('Health', {}).get('Status') != 'healthy'):
            raise RuntimeError('Pinned API/cleanup worker is not healthy')
    if database != {'schema': '20261012_physical_membership', 'maintenance': False, 'owner': None}:
        raise RuntimeError('Current schema or maintenance differs')
    return {'completed': True, 'source_commit': commit, 'source_sha256': sha256,
            'target_schema': receipt['target_schema'], 'image_id': receipt['image_id']}


def run(args, data=None):
    result = subprocess.run(args, input=data, text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Read-only cloud check failed; no private command output printed')
    return result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'/opt/xiquan-backups/desktop051-cutover-[a-f0-9]{32}', args.job):
        raise RuntimeError('Wrong checkpoint path')
    if not re.fullmatch('[a-f0-9]{40}', args.commit) or not re.fullmatch('[a-f0-9]{64}', args.sha256):
        raise RuntimeError('Wrong source identity')
    folder = Path(args.job)
    if any(p.is_symlink() for p in (folder, *folder.parents, folder / 'completed.json')):
        raise RuntimeError('Linked checkpoint forbidden')
    receipt = json.loads((folder / 'completed.json').read_text())
    api = json.loads(run(['docker', 'inspect', 'xiquan-api-1']))[0]
    worker = json.loads(run(['docker', 'inspect', 'xiquan-receipt-cleanup-1']))[0]
    script = """import json
from app import create_app
from app.extensions import db
from sqlalchemy import text
with create_app().app_context():
    with db.engine.connect() as c:
        with c.begin():
            c.exec_driver_sql('SET TRANSACTION READ ONLY')
            schema=c.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
            row=c.execute(text('SELECT maintenance, maintenance_reset_id FROM business_state WHERE id=1')).one()
            print(json.dumps(dict(schema=schema, maintenance=row[0], owner=row[1])))
"""
    database = json.loads(run(['docker', 'exec', '-i', 'xiquan-api-1', 'python', '-'], script))
    result = validate(receipt, args.commit, args.sha256, api, worker, database)
    run(['docker', 'exec', 'xiquan-nginx-1', 'nginx', '-t'])
    health = json.loads(run(['curl', '--http1.1', '--fail', '--silent', '--show-error',
                             '--max-time', '30', 'https://api.pqxqxy.xyz/api/health']))
    if health.get('success') is not True or health.get('data', {}).get('database') != 'ok':
        raise RuntimeError('Public API health failed')
    for route in ('/app/', '/mobile/download', '/mobile/download-config.json'):
        status = run(['curl', '--http1.1', '--silent', '--show-error', '--max-time', '30',
                      '--output', '/dev/null', '--write-out', '%{http_code}',
                      'https://api.pqxqxy.xyz' + route])
        if status != '200':
            raise RuntimeError('Public web/mobile route failed')
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('DESKTOP051_COMPLETION_STOPPED: ' + str(error))
