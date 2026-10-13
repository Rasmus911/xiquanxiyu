"""Fail each checkpoint before its receipt; resume must skip completed work."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'deploy/cloud/scripts'), str(ROOT / 'server')]
PHASES = ['before', 'maintenance', 'rehearsal', 'after', 'after-backup', 'ready',
          'source-switch', 'paused-api', 'maintenance-release', 'normal-worker', 'cleanup', 'origin']
IDENTITY = dict(job='job-fixture', source_commit='a' * 40, source_sha256='b' * 64,
                target_schema='20261012_physical_membership', image_id='sha256:' + 'c' * 64)


@pytest.mark.parametrize('failed', PHASES)
def test_failure_preserves_receipts_and_resume_only_runs_unfinished_phases(tmp_path, failed):
    from desktop_051_deploy import Checkpoints
    trace = []
    def operation(name):
        trace.append(name)
        if name == failed: raise RuntimeError('injected')
        return {'verified': name}
    with pytest.raises(RuntimeError): Checkpoints(tmp_path, IDENTITY).run(operation)
    assert not (tmp_path / 'completed.json').exists()
    index = PHASES.index(failed)
    assert trace == PHASES[:index + 1]
    resumed = []
    Checkpoints(tmp_path, IDENTITY).run(lambda name: resumed.append(name) or {'verified': name})
    assert resumed == PHASES[index:]
    completed = json.loads((tmp_path / 'completed.json').read_text())
    assert completed['phase'] == 'completed' and completed['source_commit'] == 'a' * 40
    assert completed['origin'] == {'verified': 'origin'}


def test_receipt_identity_or_hole_cannot_authorize_resume(tmp_path):
    from desktop_051_deploy import Checkpoints
    from operations_deploy import json_write
    json_write(tmp_path / 'ready.json', dict(IDENTITY, phase='ready', result={}))
    with pytest.raises(ValueError): Checkpoints(tmp_path, IDENTITY).validate()


def test_live_migration_without_exact_after_evidence_stops_instead_of_replaying(tmp_path):
    from desktop_051_deploy import Checkpoints
    from operations_deploy import json_write
    for name in PHASES[:3]: json_write(tmp_path / (name + '.json'), dict(IDENTITY, phase=name, result={}))
    with pytest.raises(ValueError, match='Unclassified'):
        Checkpoints(tmp_path, IDENTITY).classify('20261012_physical_membership', True, 'job-fixture')


def test_release_lost_receipt_is_classified_without_clearing_foreign_maintenance(tmp_path):
    from desktop_051_deploy import Checkpoints
    from operations_deploy import json_write
    for name in PHASES[:8]: json_write(tmp_path / (name + '.json'), dict(IDENTITY, phase=name, result={}))
    with pytest.raises(ValueError, match='maintenance'):
        Checkpoints(tmp_path, IDENTITY).classify('20261012_physical_membership', True, 'another-job')
    assert Checkpoints(tmp_path, IDENTITY).classify('20261012_physical_membership', False, None) == 'release-receipt-required'


@pytest.mark.parametrize('available,restore,want', [(384, False, 384), (640, True, 640), (900, True, 640)])
def test_small_host_budget_accounts_for_only_upcoming_allocations(available, restore, want):
    from desktop_051_deploy import resource_budget
    assert resource_budget(available * 1024**2, 6 * 1024**3, restore=restore)['required_memory_mib'] == want


def test_small_host_budget_fails_closed_below_reserve():
    from desktop_051_deploy import resource_budget
    with pytest.raises(ValueError): resource_budget(639 * 1024**2, 6 * 1024**3, restore=True)


@pytest.mark.parametrize('code,category', [(1, 'exit'), (137, 'sigkill137')])
def test_command_failure_keeps_exact_private_reason_but_public_error_is_safe(tmp_path, code, category):
    from desktop_051_deploy import PrivateRunner
    with pytest.raises(ValueError) as error:
        PrivateRunner(tmp_path, lambda: 'after')([sys.executable, '-c',
            f"import sys;sys.stderr.write('postgresql://user:password@host/db');sys.exit({code})"])
    assert 'password' not in str(error.value) and category in str(error.value)
    evidence = json.loads(next(tmp_path.glob('command-*.json')).read_text(encoding='utf-8'))
    assert evidence['stderr'] == 'postgresql://user:password@host/db'
    assert evidence['exit_code'] == code and evidence['phase'] == 'after'


def test_command_timeout_retains_timeout_category(tmp_path):
    from desktop_051_deploy import PrivateRunner
    with pytest.raises(ValueError, match='timeout'):
        PrivateRunner(tmp_path, lambda: 'cleanup')([sys.executable, '-c', 'import time;time.sleep(2)'], timeout=.05)


def test_shared_restore_uses_bounded_runner_for_actual_pg_restore(tmp_path):
    from operations_backup_verify import IsolatedRestore
    commands = []
    def runner(argv, **kwargs):
        commands.append((argv, kwargs))
        if argv[:2] == ['docker', 'inspect']:
            return json.dumps([{'State': {'Running': True, 'Health': {'Status': 'healthy'}}}])
        return ''
    restore = IsolatedRestore(tmp_path, 'sha256:pg17', 'isolated', runner=runner, memory_mib=256)
    restore.start()
    restore.restore(tmp_path / 'database.backup')
    launch = next(argv for argv, _ in commands if argv[:2] == ['docker', 'run'])
    assert launch[launch.index('--memory') + 1] == '256m'
    assert launch[launch.index('--memory-swap') + 1] == '256m'
    assert not any(arg in launch for arg in ('-p', '--publish'))
    assert 'shared_buffers=16MB' in launch and 'max_parallel_maintenance_workers=0' in launch
    restore_command, options = commands[-1]
    assert restore_command[4:8] == ['pg_restore', '--exit-on-error', '--no-owner', '--no-acl']
    assert options['input_file'] == tmp_path / 'database.backup'


def test_timeout_cleanup_only_accepts_its_pinned_owned_command():
    from desktop_051_deploy import require_owned_command
    info = {'Image': 'sha256:pinned', 'Config': {'Labels': {'xiquan.desktop051.job': 'owned'}}}
    require_owned_command(info, 'owned', 'sha256:pinned')
    with pytest.raises(ValueError): require_owned_command(info, 'foreign', 'sha256:pinned')
    with pytest.raises(ValueError): require_owned_command(info, 'owned', 'sha256:other')


def test_lost_release_receipt_is_recoverable_only_for_exact_control_flag_change():
    import copy
    from desktop_051_deploy import verify_released_snapshot
    before = dict(schema_revision='20261012_physical_membership',
        control_state=dict(id=1, period_id='period', business_revision=10, policy_version=3,
                           maintenance=True, maintenance_reset_id='owned'),
        old_row_hashes=dict(business_state=dict(rows=1, sha256='owned'), members=dict(rows=2, sha256='unchanged')))
    after = copy.deepcopy(before)
    after['control_state'].update(maintenance=False, maintenance_reset_id=None)
    after['old_row_hashes']['business_state']['sha256'] = 'released'
    verify_released_snapshot(before, after, 'owned')
    after['old_row_hashes']['members']['sha256'] = 'business-write-after-release'
    with pytest.raises(ValueError): verify_released_snapshot(before, after, 'owned')


@pytest.mark.parametrize('state,category', [
    ({'Running': False, 'OOMKilled': True, 'ExitCode': 137}, 'oom'),
    ({'Running': False, 'OOMKilled': False, 'ExitCode': 137}, 'sigkill137'),
    ({'Running': False, 'OOMKilled': False, 'ExitCode': 1}, 'exit'),
    ({'Running': True, 'OOMKilled': False, 'ExitCode': 0, 'Health': {'Status': 'unhealthy', 'Log': [{'Output': 'private cause'}]}}, 'healthcheck'),
    ({'Running': True, 'OOMKilled': False, 'ExitCode': 0, 'Health': {'Status': 'starting'}}, 'timeout'),
])
def test_restore_health_failure_keeps_inspect_state_and_category(tmp_path, state, category):
    from desktop_051_deploy import PrivateRunner
    from operations_backup_verify import IsolatedRestore
    class Runner(PrivateRunner):
        def __call__(self, argv, **kwargs):
            return json.dumps([{'Id': 'owned-clone', 'State': state}]) if argv[:2] == ['docker', 'inspect'] else ''
    runner = Runner(tmp_path, lambda: 'after-backup')
    restore = IsolatedRestore(tmp_path, 'sha256:pg17', 'isolated', runner=runner,
        memory_mib=256, health_checker=lambda name: runner.healthy(name, timeout=0))
    with pytest.raises(ValueError, match='category=' + category) as error: restore.start()
    assert 'private cause' not in str(error.value)
    evidence = json.loads(next(tmp_path.glob('health-*.json')).read_text())
    assert evidence['category'] == category and evidence['phase'] == 'after-backup'
    assert evidence['container']['State'] == state
    assert restore.started  # retained for owned cleanup, never removed


def test_backup_command_surfaces_inner_category_without_raw_stderr(tmp_path):
    from desktop_051_deploy import Desktop051
    driver = Desktop051.__new__(Desktop051)
    driver.job, driver.last_phase = tmp_path, 'before'
    def command(args, **kwargs):
        path = tmp_path / Path(args[args.index('--private-evidence') + 1]).name
        path.write_text(json.dumps(dict(category='sigkill137', exit_code=137, stderr='private authentication detail')))
        raise ValueError('outer exit=1')
    driver.command = command
    with pytest.raises(ValueError, match='category=sigkill137') as error:
        driver.backup_command(['-m', 'flask', 'operations-backup', 'create'])
    assert 'private authentication' not in str(error.value)


@pytest.mark.parametrize('service,available', [('api', 639), ('receipt-cleanup', 383)])
def test_startup_admission_rejects_insufficient_current_memory_before_compose(tmp_path, monkeypatch, service, available):
    from desktop_051_deploy import Desktop051
    from types import SimpleNamespace
    driver = Desktop051.__new__(Desktop051)
    driver.job, driver.last_phase, driver.context = tmp_path, 'paused-api', {'image_id': 'sha256:pinned'}
    driver.config = lambda _: {'services': {'api': {'mem_limit': 536870912, 'memswap_limit': 536870912},
        'receipt-cleanup': {'mem_limit': 268435456, 'memswap_limit': 268435456}}}
    # A running old API overlaps; do not add its memory back to MemAvailable.
    driver.run = lambda *a, **kw: json.dumps([{'Id': 'old', 'State': {'Running': True}, 'HostConfig': {'Memory': 536870912}}])
    original_read = Path.read_text
    monkeypatch.setattr(Path, 'read_text', lambda self, *a, **kw: f'MemAvailable: {available*1024} kB\n' if str(self).replace('\\', '/') == '/proc/meminfo' else original_read(self, *a, **kw))
    monkeypatch.setattr('desktop_051_deploy.shutil.disk_usage', lambda _: SimpleNamespace(free=8*1024**3))
    calls = []
    driver.compose = lambda *a, **kw: calls.append(a)
    driver.verify_api = lambda _: {}
    with pytest.raises(ValueError, match='memory budget'):
        driver.start_api('0') if service == 'api' else driver.cleanup()
    assert not calls


def test_startup_admission_charges_verified_limit_and_rejects_missing_limit(tmp_path):
    from desktop_051_deploy import Desktop051
    driver = Desktop051.__new__(Desktop051)
    driver.job, driver.last_phase = tmp_path, 'normal-worker'
    configs = {'services': {'api': {'mem_limit': 536870912, 'memswap_limit': 536870912}}}
    driver.config = lambda _: configs
    driver.run = lambda *a, **kw: json.dumps([{'Id': 'old', 'State': {'Running': True}, 'HostConfig': {'Memory': 0}}])
    budgets = []
    driver.budget = lambda **kw: budgets.append(kw) or {'required_memory_mib': 640}
    driver.startup_budget('api')
    assert budgets == [dict(maintenance=False, allocation_mib=512)]
    configs['services']['api']['mem_limit'] = 0
    with pytest.raises(ValueError, match='limit'): driver.startup_budget('api')
    assert len(budgets) == 1


def test_operation_deadline_limits_commands_and_retains_identity_on_expiry(tmp_path, monkeypatch):
    from desktop_051_deploy import PrivateRunner, OperationDeadline
    now = [10.0]
    monkeypatch.setattr('desktop_051_deploy.time.monotonic', lambda: now[0])
    deadline = OperationDeadline(14400)
    runner = PrivateRunner(tmp_path, lambda: 'rehearsal', deadline=deadline)
    now[0] = 14411.0
    with pytest.raises(ValueError, match='category=deadline'):
        runner([sys.executable, '-c', "raise Exception('must not run')"])
    record = json.loads(next(tmp_path.glob('command-*.json')).read_text(encoding='utf-8'))
    assert record['category'] == 'deadline' and record['phase'] == 'rehearsal'
