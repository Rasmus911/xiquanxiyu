"""Guard behavior at database and subprocess boundaries; no production connection."""
import copy
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'deploy/cloud/scripts'), str(ROOT / 'server')]


def guard():
    assert (ROOT / 'deploy/cloud/scripts/desktop_049_guard.py').exists(), 'Registration guard missing'
    return importlib.import_module('desktop_049_guard')


def snapshots():
    names = ('members', 'member_transactions', 'pass_cards', 'stock_items', 'employees',
             'account_access_policies', 'audit_logs', 'business_state', 'alembic_version')
    before = dict(schema='20261007_ordering_cost', roles='unchanged', audit_valid=True,
                  tables={n: dict(rows=2, sha256='retained', columns={'id': 'VARCHAR'}) for n in names},
                  owners={n: 'owner' for n in names}, grants={n: ['original ACL'] for n in names})
    after = copy.deepcopy(before)
    after['schema'] = '20261008_registration_token'
    for name in ('registration_token_state', 'registration_rate_limits', 'registration_receipts', 'registration_token_views'):
        after['tables'][name] = dict(rows=0, sha256='empty', columns={})
        after['owners'][name] = 'owner'
        after['grants'][name] = []
    return before, after


def test_additive_compare_accepts_empty_security_tables():
    guard().compare(*snapshots())


@pytest.mark.parametrize('mutation', ['schema', 'balance', 'pass', 'stock', 'employee', 'policy', 'grant', 'role', 'new_rows'])
def test_compare_rejects_every_existing_data_or_authority_change(mutation):
    g = guard()
    before, after = snapshots()
    table = {'balance': 'members', 'pass': 'pass_cards', 'stock': 'stock_items',
             'employee': 'employees', 'policy': 'account_access_policies'}.get(mutation)
    if table:
        after['tables'][table]['sha256'] = 'changed'
    elif mutation == 'schema':
        before['schema'] = '20260827_visit_party_link'
    elif mutation == 'grant':
        after['grants']['employees'] = ['all privileges']
    elif mutation == 'role':
        after['roles'] = 'different'
    else:
        after['tables']['registration_receipts']['rows'] = 1
    with pytest.raises(g.GuardError):
        g.compare(before, after)


def test_security_rehearsal_rejects_live_database_before_any_write():
    g = guard()
    from sqlalchemy.engine import make_url
    with pytest.raises(g.GuardError, match='isolated'):
        g.require_isolated(make_url('postgresql://localhost/production'))


def test_low_memory_budget_uses_existing_512_and_768_mib_boundaries():
    guard()
    from stock_deploy import require_resource_budget
    assert require_resource_budget(512 * 1024**2, 6 * 1024**3)['required_memory_mib'] == 512
    assert require_resource_budget(768 * 1024**2, 6 * 1024**3, include_restore=True)['required_memory_mib'] == 768


def test_remote_secret_setup_preserves_valid_value_and_private_backup(tmp_path):
    guard()
    deploy = importlib.import_module('desktop_049_deploy')
    env = tmp_path / '.env'
    env.write_text('UNCHANGED=keep\n')
    backup = tmp_path / 'private-backup'
    value = deploy.ensure_registration_secret(env, backup)
    assert len(value.encode()) >= 32
    assert backup.read_text() == 'UNCHANGED=keep\n'
    assert 'UNCHANGED=keep\n' in env.read_text()
    original = env.read_bytes()
    assert deploy.ensure_registration_secret(env, backup) == value
    assert env.read_bytes() == original
    env.write_text('REGISTRATION_TOKEN_SECRET=short\n')
    with pytest.raises(deploy.DeploymentError, match='invalid'):
        deploy.ensure_registration_secret(env, backup)


@pytest.mark.parametrize('failure', ['schema', 'snapshot', 'resources', 'image'])
def test_final_gate_rejects_unsafe_state_before_api_stop(monkeypatch, failure):
    guard()
    deploy = importlib.import_module('desktop_049_deploy')
    driver = object.__new__(deploy.Desktop049)
    driver.api_stop_started = False
    driver.pre_stop_snapshot = {'retained': 'baseline'}
    driver.guard = lambda mode: {'retained': 'changed' if failure == 'snapshot' else 'baseline'}
    events = []
    driver.compose = lambda *args: events.append(args)
    driver.phase = lambda name: events.append(name)
    # Controlled image subprocess result: the validation under test must reject it.
    driver.verify_pinned_image = lambda: (_ for _ in ()).throw(deploy.DeploymentError('Image source bytes differ')) if failure == 'image' else None
    live = {'pg_major': 17, 'schema_revision': 'unexpected' if failure == 'schema' else deploy.OLD,
            'pending_resets': [], 'business_state': {'maintenance': False, 'policy_version': 1},
            'active_policy': {'policy_version': 1}}
    monkeypatch.setattr(deploy, 'query_cloud_state', lambda: live)
    def resources(*args, **kwargs):
        from stock_deploy import require_resource_budget
        return require_resource_budget((500 if failure == 'resources' else 800) * 1024**2, 6 * 1024**3)
    monkeypatch.setattr(deploy, 'check_resources', resources)
    with pytest.raises(deploy.DeploymentError):
        driver.stop_writes_with_restore_budget({})
    assert ('stop', 'api') not in events
    assert driver.api_stop_started is False


def test_pinned_image_probe_rejects_wrong_payload(monkeypatch, tmp_path):
    guard()
    deploy = importlib.import_module('desktop_049_deploy')
    driver = object.__new__(deploy.Desktop049)
    driver.source = tmp_path
    driver.context = {'image_id': 'sha256:fixture'}
    server = tmp_path / 'server'
    server.mkdir()
    (server / 'app').mkdir()
    (server / 'migrations').mkdir()
    (server / 'run.py').write_text('# reviewed\n')
    (server / 'docker-entrypoint.sh').write_text('# reviewed\n')
    (server / 'requirements.txt').write_text('Flask==3.0.0\n')
    from operations_offline_build import requirements_digest
    monkeypatch.setattr(deploy, 'probe_image', lambda *args, **kwargs: {
        'requirements_sha256': requirements_digest(b'Flask==3.0.0\n'), 'python': [3, 12], 'compatible': True,
        'pg_dump': 'pg_dump (PostgreSQL) 17.1', 'pg_restore': 'pg_restore (PostgreSQL) 17.1', 'payload': {'run.py': 'wrong'}})
    assert callable(getattr(driver, 'verify_pinned_image', None)), 'Pinned recovery image verification missing'
    with pytest.raises(deploy.DeploymentError, match='Image source'):
        driver.verify_pinned_image()


@pytest.mark.parametrize('changed_sms', [False, True])
def test_compose_comparison_allows_stage_paths_only_and_preserves_sms(monkeypatch, tmp_path, changed_sms):
    import json
    guard()
    deploy = importlib.import_module('desktop_049_deploy')
    driver = object.__new__(deploy.Desktop049)
    driver.source = tmp_path / 'stage/xiquan'
    project = tmp_path / 'live/xiquan'
    monkeypatch.setattr(deploy, 'PROJECT', project)
    configs = [dict(services={'api': {'environment': {'SMS_ENABLED': '1'}},
                              'nginx': {'volumes': [{'source': str(project / 'deploy/cloud/web')}]}}),
               dict(services={'api': {'environment': {'SMS_ENABLED': '0' if changed_sms else '1', 'REGISTRATION_TOKEN_SECRET': ''}},
                              'nginx': {'volumes': [{'source': str(driver.source / 'deploy/cloud/web')}]}})]
    monkeypatch.setattr(deploy, 'run', lambda args: json.dumps(configs.pop(0)))
    if changed_sms:
        with pytest.raises(deploy.DeploymentError, match='Compose differs'): driver.validate_compose_change()
    else:
        driver.validate_compose_change()
