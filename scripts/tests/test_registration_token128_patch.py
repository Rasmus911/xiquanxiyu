"""The narrow patch must stop on drift before touching the existing API."""
import hashlib
import importlib
from pathlib import Path
import subprocess
import sys
import copy

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy/cloud/scripts'))


def inputs():
    before = subprocess.check_output(['git', 'show', '4f11626373298754d2e0ceacd82ae7ff5dd71204:server/app/api/mobile.py'], cwd=ROOT)
    incoming = (ROOT / 'server/app/api/mobile.py').read_bytes()
    return before, incoming, hashlib.sha256(incoming).hexdigest()


def test_only_reviewed_capability_patch_and_baseline_are_accepted():
    patch = importlib.import_module('registration_token128_patch')
    before, incoming, digest = inputs()
    patch.verify_patch(before, incoming, digest)
    patch.verify_patch(incoming, incoming, digest)
    patch.verify_patch(before.replace(b'\n', b'\r\n'), incoming, digest)


@pytest.mark.parametrize('mutation', ['before', 'incoming', 'hash'])
def test_changed_source_or_transport_hash_stops_patch(mutation):
    patch = importlib.import_module('registration_token128_patch')
    before, incoming, digest = inputs()
    if mutation == 'before': before += b'\n# unreviewed local server change'
    if mutation == 'incoming': incoming += b'\n# unreviewed patch change'; digest = hashlib.sha256(incoming).hexdigest()
    if mutation == 'hash': digest = '0' * 64
    with pytest.raises(ValueError): patch.verify_patch(before, incoming, digest)


def runtime_fixture():
    service = {'environment': {'RESET_WORKER_ENABLED': '1', 'SECRET_KEY': 'dev-only-unchanged'},
               'networks': {'default': None}, 'volumes': [{'type': 'bind', 'source': '/opt/xiquan/data',
                 'target': '/app/data', 'read_only': False}], 'restart': 'unless-stopped'}
    image = {'Env': ['PATH=/usr/bin', 'RESET_WORKER_ENABLED=0'], 'Cmd': ['python', 'run.py'],
             'Entrypoint': ['/app/docker-entrypoint.sh'], 'User': 'xiquan', 'WorkingDir': '/app'}
    runtime = {'Config': {'Env': ['PATH=/usr/bin', 'RESET_WORKER_ENABLED=1', 'SECRET_KEY=dev-only-unchanged'],
                   'Cmd': ['python', 'run.py'], 'Entrypoint': ['/app/docker-entrypoint.sh'],
                   'User': 'xiquan', 'WorkingDir': '/app'},
               'Mounts': [{'Type': 'bind', 'Source': '/opt/xiquan/data', 'Destination': '/app/data', 'RW': True}],
               'NetworkSettings': {'Networks': {'xiquan_default': {}}},
               'HostConfig': {'PortBindings': {}, 'RestartPolicy': {'Name': 'unless-stopped'},
                              'Memory': 0, 'NanoCpus': 0, 'ReadonlyRootfs': False}}
    config = {'services': {'api': service}, 'networks': {'default': {'name': 'xiquan_default'}}}
    return config, image, runtime


def test_resolved_runtime_matches_before_cutover():
    patch = importlib.import_module('registration_token128_patch')
    config, image, runtime = runtime_fixture()
    patch.verify_runtime(config, image, runtime)


@pytest.mark.parametrize('changed', ['environment', 'worker', 'command', 'mount', 'network', 'memory'])
def test_runtime_drift_is_rejected_before_cutover(changed):
    patch = importlib.import_module('registration_token128_patch')
    config, image, runtime = runtime_fixture()
    config = copy.deepcopy(config)
    api = config['services']['api']
    if changed == 'environment': api['environment']['SECRET_KEY'] = 'different'
    if changed == 'worker': api['environment']['RESET_WORKER_ENABLED'] = '0'
    if changed == 'command': api['command'] = ['other']
    if changed == 'mount': api['volumes'][0]['source'] = '/different'
    if changed == 'network': config['networks']['default']['name'] = 'different'
    if changed == 'memory': api['mem_limit'] = 384 * 1024 * 1024
    with pytest.raises(ValueError): patch.verify_runtime(config, image, runtime)


def test_resolved_json_escapes_dollars_without_reinterpreting_secrets():
    patch = importlib.import_module('registration_token128_patch')
    assert patch.escape_compose({'environment': {'SECRET': 'dev-only-a${NAME}$b'}}) == {
        'environment': {'SECRET': 'dev-only-a$${NAME}$$b'}}


def test_origin_health_uses_http11_without_disabling_tls_or_http_failure_checks():
    # Without an explicit protocol, curl can negotiate HTTP/2 and abort a
    # healthy cutover with exit 16. Check the command at the external boundary.
    patch = importlib.import_module('registration_token128_patch')
    assert callable(getattr(patch, 'verify_origin_health', None)), 'Explicit origin health verifier missing'
    commands = []
    patch.verify_origin_health(commands.append)
    assert commands == [[
        'curl', '--http1.1', '--fail', '--silent', '--show-error', '--max-time', '20',
        '--resolve', 'api.pqxqxy.xyz:443:127.0.0.1', '--noproxy', 'api.pqxqxy.xyz',
        'https://api.pqxqxy.xyz/api/health',
    ]]
