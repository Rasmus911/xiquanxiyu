import copy
import importlib.util
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_operations_upgrade import legacy_app

SCRIPT = Path(__file__).resolve().parents[2] / 'deploy/cloud/scripts/operations_preview_recovery.py'


@pytest.fixture
def recovery(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('preview_recovery_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def posix_permissions(monkeypatch, root):
    # Run the real POSIX permission branch on Windows without modifying real ACLs.
    from app import operations_backup
    environment = dict(vars(os)); environment.update(name='posix', getuid=lambda: 0)
    monkeypatch.setattr(operations_backup, 'os', SimpleNamespace(**environment))
    original = Path.stat
    def info(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        values = list(result)
        values[0] = stat.S_IFMT(result.st_mode) | (0o700 if path == root or root in path.parents else 0o755)
        values[4] = 0
        return os.stat_result(values)
    monkeypatch.setattr(Path, 'stat', info)


def test_existing_root_output_bug_is_reproduced_but_a_private_child_is_valid(legacy_app, monkeypatch):
    from app.operations_backup import BackupReceiptError, private_path
    app, _ = legacy_app
    root = Path(app.config['RESET_PRIVATE_DIR']); root.mkdir()
    child = root / 'child'; child.mkdir()
    posix_permissions(monkeypatch, root)
    with pytest.raises(BackupReceiptError, match='owner-only'):
        private_path(root, directory=True)
    assert private_path(child, directory=True) == child


def test_preview_uses_real_cli_in_private_child_and_retains_original_contract(legacy_app, recovery, monkeypatch):
    app, _ = legacy_app
    root = Path(app.config['RESET_PRIVATE_DIR']); root.mkdir()
    posix_permissions(monkeypatch, root)
    monkeypatch.setattr(recovery, 'MOUNT', str(root), raising=False)
    operations = object.__new__(recovery.PrivateOutputDeployment)
    operations.job = root
    def cli(arguments, **kwargs):
        result = app.test_cli_runner().invoke(args=arguments)
        assert result.exit_code == 0, result.exception
        return result.output.strip()
    operations.maintenance = cli
    preview = operations.preview()
    assert preview['can_apply'] is True
    assert (root / 'preview.json').is_file()
    stored = json.loads((root / 'preview.json').read_text(encoding='utf-8'))
    assert len(stored['new_wristband_numbers']) == 100
    assert stored['old_wristband_numbers'][0] == '8001'
    assert stored['retained_products']
    assert (root / 'preview.json').stat().st_mode & 0o077 == 0


def evidence_fixture():
    state = {'schema_revision': '20261004_catalog_packages', 'pg_major': 17,
        'open_visits': 0, 'unresolved_wristbands': [], 'pending_resets': 0,
        'business_state': {'maintenance': False, 'policy_version': 1},
        'active_policy': {'policy_version': 1}}
    rehearsal = {'pg_major': 17, 'actual_migration': True, 'actual_restore': True,
        'actual_apply': True, 'role_and_lock_exercise': True, 'production_unchanged': True,
        'active_wristbands': 100, 'formal_items': 42}
    candidate = {'dump_sha256': 'a' * 64, 'dump_size': 42,
        'checks': {'identity': {'alembic_revision': '20261004_catalog_packages'}}}
    receipt = {'dump_sha256': 'a' * 64, 'dump_size': 42,
        'restore': {'status': 'verified', 'pg_major': 17, 'source_server_id': 'production', 'restored_server_id': 'clone'}}
    return state, rehearsal, receipt, candidate


def test_recovery_requires_completed_rehearsal_migration_and_actual_restore(recovery):
    state, rehearsal, receipt, candidate = evidence_fixture()
    recovery.require_post_migration_checkpoint('private-business-preview', state, rehearsal, receipt, candidate, 'a' * 64)
    for key, value in [('actual_migration', False), ('actual_restore', False), ('actual_apply', False),
                       ('role_and_lock_exercise', False), ('production_unchanged', False)]:
        changed = dict(rehearsal); changed[key] = value
        with pytest.raises(recovery.DeploymentError):
            recovery.require_post_migration_checkpoint('private-business-preview', state, changed, receipt, candidate, 'a' * 64)
    for phase in ['build-new-api-image', 'explicit-owner-schema-migration', 'completed-cloud-cutover']:
        with pytest.raises(recovery.DeploymentError):
            recovery.require_post_migration_checkpoint(phase, state, rehearsal, receipt, candidate, 'a' * 64)
    changed = copy.deepcopy(receipt); changed['restore']['restored_server_id'] = 'production'
    with pytest.raises(recovery.DeploymentError):
        recovery.require_post_migration_checkpoint('private-business-preview', state, rehearsal, changed, candidate, 'a' * 64)
    with pytest.raises(recovery.DeploymentError):
        recovery.require_post_migration_checkpoint('private-business-preview', state, rehearsal, receipt, candidate, 'b' * 64)


def test_snapshot_inspection_uses_private_child_and_preserves_expected_filename(legacy_app, recovery, monkeypatch):
    import ast
    from app.operations_backup import write_private_json
    app, _ = legacy_app
    root = Path(app.config['RESET_PRIVATE_DIR']); root.mkdir()
    posix_permissions(monkeypatch, root)
    monkeypatch.setattr(recovery, 'MOUNT', root.as_posix())
    operations = object.__new__(recovery.PrivateOutputDeployment); operations.job = root
    checks = {'tables': {'members': {'rows': 1, 'sha256': 'a' * 64}}, 'audit_valid': True}
    def inspect(arguments, *, python=False):
        assert python is True
        tree = ast.parse(arguments[1])
        destinations = [node.args[0].value for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Path']
        assert len(destinations) == 1
        destination = Path(destinations[0])
        assert destination.parent != root and root in destination.parents
        write_private_json(destination, checks)
        return ''
    operations.maintenance = inspect
    operations.inspect_current('pre-apply-checks.json')
    assert json.loads((root / 'pre-apply-checks.json').read_text()) == checks
    with pytest.raises(FileExistsError): operations.inspect_current('pre-apply-checks.json')
    assert json.loads((root / 'pre-apply-checks.json').read_text()) == checks


def test_failed_command_keeps_raw_error_private_and_does_not_echo_it(recovery, tmp_path, monkeypatch):
    from subprocess import CompletedProcess
    operations = object.__new__(recovery.PrivateOutputDeployment)
    operations.job = tmp_path; operations.context = {'network': 'private', 'new_image': 'verified'}
    def failure(argv, **kwargs):
        assert argv[:4] == ['docker', 'run', '--rm', '--user']
        return CompletedProcess(argv, 2, '', 'fixture-only-private-error')
    monkeypatch.setattr(recovery.subprocess, 'run', failure)
    with pytest.raises(recovery.DeploymentError) as error:
        operations.maintenance(['operations-upgrade', 'preview'])
    assert 'fixture-only-private-error' not in str(error.value)
    evidence = list(tmp_path.glob('preview-recovery-evidence-*/command-failure.json'))
    assert len(evidence) == 1
    assert json.loads(evidence[0].read_text())['stderr'] == 'fixture-only-private-error'
