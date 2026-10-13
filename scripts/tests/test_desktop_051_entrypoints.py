import copy
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'deploy/cloud/scripts'), str(ROOT / 'server')]


def test_merged_compose_allows_only_checked_cleanup_limits_and_probe():
    from desktop_051_deploy import validate_merged_compose, CLEANUP_PROBE
    old = {'services': {'api': {'environment': {'DATABASE_URL': 'runtime', 'RUNTIME_DATABASE_URL': 'runtime'}},
          'receipt-cleanup': {'entrypoint': ['python', '-m', 'app.receipt_cleanup_worker'],
            'environment': {'DATABASE_URL': 'owner', 'MAINTENANCE_DATABASE_URL': 'owner'},
            'networks': {'backend': None}, 'mem_limit': 134217728, 'memswap_limit': 134217728,
            'healthcheck': {'test': ['CMD', 'python', '-m', 'app.receipt_cleanup_worker', '--health']}}}}
    new = copy.deepcopy(old)
    new['services']['api'].update(mem_limit=536870912, memswap_limit=536870912)
    new['services']['receipt-cleanup'].update(mem_limit=268435456, memswap_limit=268435456,
        healthcheck={'test': ['CMD', 'python', '-c', CLEANUP_PROBE], 'interval': '10s', 'timeout': '3s', 'start_period': '15s', 'retries': 6})
    validate_merged_compose(old, new)
    for mutate in ('owner-api', 'port', 'other-service', 'limit', 'build', 'api-limit'):
        changed = copy.deepcopy(new)
        if mutate == 'owner-api': changed['services']['api']['environment']['MAINTENANCE_DATABASE_URL'] = 'owner'
        elif mutate == 'port': changed['services']['receipt-cleanup']['ports'] = [9999]
        elif mutate == 'other-service': changed['services']['api']['command'] = 'other'
        elif mutate == 'build': changed['services']['api']['build'] = {'dockerfile': 'unreviewed'}
        elif mutate == 'api-limit': changed['services']['api']['mem_limit'] = 268435456
        else: changed['services']['receipt-cleanup']['mem_limit'] = 536870912
        with pytest.raises(ValueError): validate_merged_compose(old, changed)


def test_real_compose_json_decimal_strings_allow_reviewed_upgrade_from_unlimited_api():
    from desktop_051_deploy import validate_merged_compose, CLEANUP_PROBE
    # Actual ECS `docker compose config --format json` serializes byte counts as strings.
    old = {'services': {'api': {'environment': {'DATABASE_URL': 'runtime', 'RUNTIME_DATABASE_URL': 'runtime'}},
        'receipt-cleanup': {'entrypoint': ['python', '-m', 'app.receipt_cleanup_worker'],
            'environment': {'DATABASE_URL': 'owner', 'MAINTENANCE_DATABASE_URL': 'owner'},
            'networks': {'backend': None}, 'mem_limit': '134217728', 'memswap_limit': '134217728',
            'healthcheck': {'test': ['CMD', 'python', '-m', 'app.receipt_cleanup_worker', '--health']}}}}
    new = copy.deepcopy(old)
    new['services']['api'].update(mem_limit='536870912', memswap_limit='536870912')
    new['services']['receipt-cleanup'].update(mem_limit='268435456', memswap_limit='268435456',
        healthcheck={'test': ['CMD', 'python', '-c', CLEANUP_PROBE], 'interval': '10s',
                     'timeout': '3s', 'start_period': '15s', 'retries': 6})
    original = copy.deepcopy((old, new))
    validate_merged_compose(old, new)
    assert (old, new) == original  # Normalization cannot rewrite evidence or credentials.
    changed = copy.deepcopy(new)
    changed['services']['api']['memswap_limit'] = '1073741824'
    with pytest.raises(ValueError): validate_merged_compose(old, changed)


@pytest.mark.parametrize('value,expected', [('536870912', 536870912), (536870912, 536870912)])
def test_compose_config_boundary_normalizes_bytes_for_startup_admission(value, expected):
    from desktop_051_deploy import Desktop051
    driver = Desktop051.__new__(Desktop051)
    driver.run = lambda *args, **kwargs: json.dumps({'services': {'api': {
        'mem_limit': value, 'memswap_limit': value,
        'environment': {'DATABASE_URL': 'private-runtime'}, 'pids_limit': '64'}}})
    config = driver.config(Path('candidate.yml'))
    assert config['services']['api']['mem_limit'] == expected
    assert config['services']['api']['memswap_limit'] == expected
    assert config['services']['api']['environment'] == {'DATABASE_URL': 'private-runtime'}
    assert config['services']['api']['pids_limit'] == '64'


@pytest.mark.parametrize('value', ['512m', '536870912x', '536870912.0', -1, True, 536870912.0, None])
def test_compose_config_boundary_rejects_malformed_or_lossy_memory_values(value):
    from desktop_051_deploy import Desktop051
    driver = Desktop051.__new__(Desktop051)
    driver.run = lambda *args, **kwargs: json.dumps({'services': {'api': {'mem_limit': value}}})
    with pytest.raises(ValueError, match='memory byte count'):
        driver.config(Path('candidate.yml'))


@pytest.mark.parametrize('beat,expected', [(None, 1), ({'ok': False, 'checked_at': 99}, 1),
    ({'ok': True, 'checked_at': 99}, 0), ({'ok': True, 'checked_at': -21}, 1), ({'ok': True, 'checked_at': 101}, 1)])
def test_probe_executes_with_only_standard_library(beat, expected, tmp_path):
    from desktop_051_deploy import CLEANUP_PROBE
    path = tmp_path / 'beat.json'
    if beat is not None: path.write_text(json.dumps(beat))
    script = CLEANUP_PROBE.replace("'/tmp/xiquan-receipt-cleanup-health.json'", repr(str(path))).replace('time.time()', '100')
    result = subprocess.run([sys.executable, '-I', '-S', '-c', script], capture_output=True)
    assert result.returncode == expected and not result.stderr


@pytest.mark.parametrize('arguments', [[], ['-Mode', 'resume', '-BundlePath', 'missing', '-ExpectedSha256', 'invalid', '-SourceCommit', 'a'*40]])
def test_powershell_rejects_invalid_inputs_before_any_transport(arguments):
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        str(ROOT / 'scripts/invoke-desktop-051.ps1'), *arguments], capture_output=True, text=True, encoding='utf-8', errors='replace')
    assert (ROOT / 'scripts/invoke-desktop-051.ps1').exists()
    assert result.returncode != 0 and 'UPLOAD' not in result.stdout


@pytest.mark.parametrize('schema,accepted', [('20261011_service_receipts', True),
    ('20261012_physical_membership', True), ('20261008_registration_token', False), ('future-head', False)])
def test_receipt_worker_schema_gate_is_exact(schema, accepted):
    from app.receipt_cleanup_worker import require_receipt_schema
    from sqlalchemy import create_engine
    with create_engine('sqlite://').begin() as connection:
        connection.exec_driver_sql('CREATE TABLE alembic_version(version_num TEXT)')
        connection.exec_driver_sql('INSERT INTO alembic_version VALUES (?)', (schema,))
        if accepted: require_receipt_schema(connection)
        else:
            with pytest.raises(RuntimeError): require_receipt_schema(connection)


def bundle_fixture(tmp_path, *, private=False):
    from desktop_051_deploy import TOOLS
    names = ['deploy/cloud/scripts/' + name for name in TOOLS] + [
        'server/app/member_cards.py', 'server/app/member_payment.py',
        'server/migrations/versions/20261012_physical_membership.py', 'client/package.json', 'mobile/version.json']
    content = {name: (ROOT / name).read_bytes() for name in names}
    if private: content['server/instance/database.backup'] = b'private database fixture'
    manifest = dict(schema=1, label='SOURCE/WEB', source_commit='a'*40, asset_source_commit='a'*40,
        desktop_version='0.5.1', android_version='1.2.9', android_version_code=16,
        schema_head='20261012_physical_membership', targets=['win10-x86','win10-x64','win11-x86','win11-x64'],
        files=[dict(file=name, size=len(data), sha256=hashlib.sha256(data).hexdigest()) for name, data in content.items()])
    path = tmp_path / 'source.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in content.items(): archive.writestr('xiquan/' + name, data)
        archive.writestr('xiquan/source-manifest.json', json.dumps(manifest))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize('private', [False, True])
def test_local_entrypoint_validates_complete_bundle_without_transport(tmp_path, private):
    path, digest = bundle_fixture(tmp_path, private=private)
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
        str(ROOT / 'scripts/invoke-desktop-051.ps1'), '-Mode', 'preflight', '-BundlePath', str(path),
        '-ExpectedSha256', digest, '-SourceCommit', 'a'*40, '-StageOnly'], capture_output=True,
        text=True, encoding='utf-8', errors='replace')
    assert result.returncode == (1 if private else 0), result.stderr
    assert 'UPLOAD' not in result.stdout


@pytest.mark.parametrize('status,altered', [('302', False), ('200', True), ('200', False)])
def test_http_proof_requires_200_and_exact_asset_bytes(tmp_path, status, altered):
    from desktop_051_deploy import Desktop051
    driver = Desktop051.__new__(Desktop051)
    driver.job = tmp_path
    expected = b'<html>\n  preserved whitespace\n</html>\n'
    driver.manifest = {'files': [dict(file='client/dist/index.html', sha256=hashlib.sha256(expected).hexdigest())]}
    driver.result = lambda _: {'compatibility': {'scope': 'isolated endpoints'}}
    driver.verify_api = lambda _: None
    driver.protected = lambda: None
    def runner(argv, **kwargs):
        assert '--http1.1' in argv and '--output' in argv
        output = Path(argv[argv.index('--output') + 1])
        if argv[-1].endswith('/api/health'):
            output.write_bytes(b'{"success":true,"data":{"database":"ok"}}')
        else: output.write_bytes(expected.strip() if altered else expected)
        return status
    driver.run = runner
    if status != '200' or altered:
        with pytest.raises(ValueError): driver.origin()
    else:
        proof = driver.origin()
        assert proof['hashes']['public:client/dist/index.html'] == hashlib.sha256(expected).hexdigest()


def test_actual_compose_yaml_has_only_approved_cleanup_change_and_runnable_probe(tmp_path):
    # Docker merge is an ECS preflight gate. Here parse actual YAML with the
    # already-installed JS YAML parser; never call this an actual Docker merge.
    from desktop_051_deploy import validate_merged_compose
    old = subprocess.run(['git', 'show', '8eb00bdf667bb18905c83014254a901ddcb45b4e:deploy/cloud/docker-compose.prod.yml'],
                         cwd=ROOT, capture_output=True, check=True).stdout
    new = (ROOT / 'deploy/cloud/docker-compose.prod.yml').read_bytes()
    def parse(content):
        script = "const fs=require('fs'),yaml=require('./client/node_modules/js-yaml');process.stdout.write(JSON.stringify(yaml.load(fs.readFileSync(0,'utf8'))))"
        result = subprocess.run(['node', '-e', script], input=content, cwd=ROOT, capture_output=True, check=True)
        config = json.loads(result.stdout)
        for service in config['services'].values():
            for key in ('mem_limit', 'memswap_limit'):
                if key in service: service[key] = int(service[key][:-1]) * 1024**2
        return config
    before, after = parse(old), parse(new)
    assert after['services']['api']['mem_limit'] == after['services']['api']['memswap_limit'] == 536870912
    validate_merged_compose(before, after)
    probe = after['services']['receipt-cleanup']['healthcheck']['test']
    script = probe[3].replace("'/tmp/xiquan-receipt-cleanup-health.json'", repr(str(tmp_path / 'missing')))
    assert subprocess.run([sys.executable, '-I', '-S', '-c', script], capture_output=True).returncode == 1


def test_streaming_transport_timeout_retains_exact_job_and_filters_private_output(tmp_path):
    # A real bounded child emits job evidence, then stalls: never replay it.
    helper = ROOT / 'scripts/lib/desktop-051-transport.ps1'
    receipt = tmp_path / 'transport.json'
    stage = '/opt/xiquan-releases/desktop051-stage-' + 'a' * 32
    job = '/opt/xiquan-backups/desktop051-cutover-' + 'b' * 32
    child = ("import time;print('PRIVATE_DESKTOP_JOB=" + job + "',flush=True);"
             "print('DESKTOP051_PHASE=before',flush=True);print('password=DO_NOT_EXPOSE',flush=True);time.sleep(10)")
    def quoted(value): return "'" + str(value).replace("'", "''") + "'"
    script = (f". {quoted(helper)}; $r=Invoke-Desktop051Operation -Executable {quoted(sys.executable)} "
        f"-Arguments @('-u','-c',{quoted(child)}) -TimeoutSeconds 1 -IdentityFile {quoted(receipt)} "
        f"-Stage {quoted(stage)}; $r | ConvertTo-Json -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-Command', script], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
    assert result.returncode == 0, result.stderr
    assert job in result.stdout and 'DESKTOP051_PHASE=before' in result.stdout
    assert 'DO_NOT_EXPOSE' not in result.stdout + result.stderr
    saved = json.loads(receipt.read_text(encoding='utf-8-sig'))
    assert saved['Job'] == job and saved['Stage'] == stage and saved['TimedOut'] is True
    assert saved['Phase'] == 'before' and saved['AutomaticRetry'] is False


def test_transport_discards_identity_spoof_and_retains_provided_resume_job(tmp_path):
    helper = ROOT / 'scripts/lib/desktop-051-transport.ps1'
    receipt = tmp_path / 'transport.json'
    stage = '/opt/xiquan-releases/desktop051-stage-' + 'a' * 32
    job = '/opt/xiquan-backups/desktop051-cutover-' + 'b' * 32
    def quoted(value): return "'" + str(value).replace("'", "''") + "'"
    child = "print('PRIVATE_DESKTOP_JOB=/tmp/password-secret');print('DESKTOP051_PHASE=before password-secret')"
    script = (f". {quoted(helper)}; Invoke-Desktop051Operation -Executable {quoted(sys.executable)} "
        f"-Arguments @('-c',{quoted(child)}) -TimeoutSeconds 2 -IdentityFile {quoted(receipt)} "
        f"-Stage {quoted(stage)} -Job {quoted(job)} | ConvertTo-Json -Compress")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-Command', script], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
    assert result.returncode == 0, result.stderr
    assert 'password-secret' not in result.stdout + result.stderr
    assert json.loads(receipt.read_text(encoding='utf-8-sig'))['Job'] == job
