"""Real deployment guards; Docker is an external boundary, never ECS in tests."""
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'deploy/cloud/scripts/operations_deploy.py'


@pytest.fixture
def deploy(monkeypatch):
    assert SCRIPT.is_file(), 'Reviewed maintenance deployment driver is missing'
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('operations_deploy_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state():
    return {'schema_revision': '20261003_preserve_administrators', 'pg_major': 17,
        'open_visits': 0, 'unresolved_wristbands': None, 'pending_resets': 0,
        'business_state': {'maintenance': False, 'policy_version': 1},
        'active_policy': {'policy_version': 1}}


@pytest.mark.parametrize('field,value', [('open_visits', 1), ('unresolved_wristbands', ['8004']),
    ('pending_resets', 1), ('pg_major', 16)])
def test_blocked_database_never_enters_maintenance(deploy, field, value):
    current = state()
    current[field] = value
    with pytest.raises(deploy.DeploymentError): deploy.require_idle(current)


def test_maintenance_owned_by_another_task_is_not_cleared(deploy):
    current = state()
    current['business_state']['maintenance'] = True
    with pytest.raises(deploy.DeploymentError): deploy.require_idle(current)


def test_verified_restore_requires_full_rows_and_different_physical_cluster(deploy):
    source = {'server': {'pg_major': 17, 'system_identifier': 'source-id'},
        'tables': {'members': {'rows': 2, 'sha256': 'a' * 64}}}
    restored = copy.deepcopy(source)
    with pytest.raises(deploy.DeploymentError): deploy.verify_full_restore(source, restored)
    restored['server']['system_identifier'] = 'isolated-id'
    deploy.verify_full_restore(source, restored)
    restored['tables']['members']['sha256'] = 'b' * 64
    with pytest.raises(deploy.DeploymentError): deploy.verify_full_restore(source, restored)


def test_postapply_does_not_tolerate_financial_or_account_row_changes(deploy):
    before = {name: {'rows': 1, 'sha256': 'a' * 64} for name in
        ['members', 'payments', 'employees', 'order_items', 'access_policies',
         'catalog_items', 'wristbands', 'system_settings', 'business_state', 'audit_logs']}
    after = copy.deepcopy(before)
    after['catalog_items']['sha256'] = 'b' * 64
    deploy.verify_retained_rows(before, after)
    for table in ['members', 'payments', 'employees', 'order_items', 'access_policies']:
        changed = copy.deepcopy(after)
        changed[table]['sha256'] = 'c' * 64
        with pytest.raises(deploy.DeploymentError): deploy.verify_retained_rows(before, changed)


def test_preview_confirmation_is_bound_to_this_attempt(deploy):
    job = {'status': 'preview_ready', 'preview_sha256': 'a' * 64}
    deploy.require_confirmation(job, 'a' * 64)
    with pytest.raises(deploy.DeploymentError): deploy.require_confirmation(job, 'b' * 64)
    job['status'] = 'preparing'
    with pytest.raises(deploy.DeploymentError): deploy.require_confirmation(job, 'a' * 64)


def test_private_environment_rejects_injection_without_printing_value(deploy, tmp_path):
    target = tmp_path / 'private.env'
    with pytest.raises(deploy.DeploymentError) as error:
        deploy.write_environment(target, {'SECRET_KEY': 'fixture-private\nMALICIOUS=1'})
    assert 'fixture-private' not in str(error.value)
    assert not target.exists()
    deploy.write_environment(target, {'SAFE_VALUE': 'fixture-only'})
    assert target.read_text() == 'SAFE_VALUE=fixture-only\n'
    with pytest.raises(deploy.DeploymentError): deploy.write_environment(target, {'SAFE_VALUE': 'overwrite'})


def test_prepare_has_no_automatic_apply_and_backup_failure_keeps_api_stopped(deploy):
    actions = []
    class Operations:
        def initial_check(self): actions.append('check')
        def stop_api(self): actions.append('stop')
        def idle_check(self): actions.append('idle')
        def legacy_backup_restore(self): actions.append('legacy'); raise deploy.DeploymentError('restore failed')
        def build_image(self): actions.append('build')
        def rehearsal(self): actions.append('rehearsal')
        def migrate(self): actions.append('migrate')
        def snapshot_restore(self): actions.append('new-backup')
        def preview(self): actions.append('preview'); return {'can_apply': True}
        def save_preview(self, _preview): actions.append('ready')
    with pytest.raises(deploy.DeploymentError): deploy.prepare(Operations())
    assert actions == ['check', 'stop', 'idle', 'legacy']


def test_prepare_requires_both_restores_before_ready(deploy):
    actions = []
    class Operations:
        def initial_check(self): actions.append('check')
        def stop_api(self): actions.append('stop')
        def idle_check(self): actions.append('idle')
        def legacy_backup_restore(self): actions.append('legacy')
        def build_image(self): actions.append('build')
        def rehearsal(self): actions.append('rehearsal')
        def migrate(self): actions.append('migrate')
        def snapshot_restore(self): actions.append('new-backup')
        def preview(self): actions.append('preview'); return {'can_apply': False, 'conflicts': ['UNFINISHED_WRISTBANDS']}
        def save_preview(self, _preview): actions.append('ready')
    with pytest.raises(deploy.DeploymentError): deploy.prepare(Operations())
    assert actions == ['check', 'stop', 'idle', 'legacy', 'build', 'rehearsal', 'migrate', 'new-backup', 'preview']


def test_isolated_rehearsal_failure_prevents_production_migration(deploy):
    actions = []
    class Operations:
        def initial_check(self): actions.append('check')
        def stop_api(self): actions.append('stop')
        def idle_check(self): actions.append('idle')
        def legacy_backup_restore(self): actions.append('legacy')
        def build_image(self): actions.append('build')
        def rehearsal(self): actions.append('rehearsal'); raise deploy.DeploymentError('isolated rehearsal failed')
        def migrate(self): actions.append('production-migration')
        def snapshot_restore(self): actions.append('production-backup')
        def preview(self): return {'can_apply': True}
        def save_preview(self, _preview): actions.append('ready')
    with pytest.raises(deploy.DeploymentError): deploy.prepare(Operations())
    assert actions == ['check', 'stop', 'idle', 'legacy', 'build', 'rehearsal']


def test_apply_verifies_evidence_and_finances_before_starting_api(deploy):
    actions = []
    class Operations:
        def confirmation_check(self, _confirm): actions.append('confirmation')
        def recheck_receipt(self): actions.append('receipt')
        def business_apply(self): actions.append('apply')
        def verify_business(self): actions.append('verify'); raise deploy.DeploymentError('balance changed')
        def install_source(self): actions.append('source')
        def start_api(self): actions.append('start')
        def publish_web(self): actions.append('web')
        def finish(self): actions.append('finish')
    with pytest.raises(deploy.DeploymentError): deploy.apply(Operations(), 'a' * 64)
    assert actions == ['confirmation', 'receipt', 'apply', 'verify']


def test_docker_ps_json_lines_require_exactly_one_real_api(deploy):
    deploy.require_single_api('{"ID":"real-one","Names":"xiquan-api-1"}\n')
    for text in ['', '{"ID":"one"}\n{"ID":"two"}', '{}', 'not-json']:
        with pytest.raises(deploy.DeploymentError): deploy.require_single_api(text)


def test_maintenance_inspection_python_is_executable_without_shell_quoting(deploy):
    operations = object.__new__(deploy.Deployment)
    captured = []
    operations.maintenance = lambda arguments, **kwargs: captured.append((arguments, kwargs))
    operations.inspect_current('after-apply-checks.json')
    assert captured[0][0][0] == '-c'
    compile(captured[0][0][1], '<actual maintenance inspection>', 'exec')


def test_restore_subprocess_uses_dump_bytes_and_sanitizes_failure(deploy, tmp_path):
    import operations_backup_verify as backup
    source = tmp_path / 'dump'
    source.write_bytes(b'actual-file-bytes')
    output = backup.run([sys.executable, '-c', 'import sys; print(sys.stdin.buffer.read().hex())'], input_file=source)
    assert output == '61637475616c2d66696c652d6279746573'
    with pytest.raises(deploy.DeploymentError) as error:
        backup.run([sys.executable, '-c', 'import sys; print("fixture-private-secret",file=sys.stderr); sys.exit(2)'])
    assert 'fixture-private-secret' not in str(error.value)


def test_schema_migration_must_preserve_every_original_data_row(deploy):
    before={name:{'rows':1,'sha256':'a'*64} for name in ['members','catalog_items','order_items','employees','alembic_version']}
    after=copy.deepcopy(before); after['alembic_version']['sha256']='b'*64
    deploy.verify_schema_data_preserved(before,after)
    for table in ['members','catalog_items','order_items','employees']:
        changed=copy.deepcopy(after); changed[table]['sha256']='c'*64
        with pytest.raises(deploy.DeploymentError): deploy.verify_schema_data_preserved(before,changed)


def test_rehearsal_role_exercise_python_compiles(deploy):
    compile(deploy.REHEARSAL_ROLE_CHECK,'<real isolated role/lock exercise>','exec')
