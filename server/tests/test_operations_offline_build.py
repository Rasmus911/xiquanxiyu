"""Offline recovery guards; tests never SSH or touch Docker/production."""
import copy
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'deploy/cloud/scripts/operations_offline_build.py'


@pytest.fixture
def recovery(monkeypatch):
    assert SCRIPT.is_file(), 'Offline image recovery helper is not implemented'
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('offline_build_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def state():
    return {'schema_revision': '20261003_preserve_administrators', 'pg_major': 17,
        'open_visits': 0, 'unresolved_wristbands': [], 'pending_resets': 0,
        'business_state': {'maintenance': False, 'policy_version': 1},
        'active_policy': {'policy_version': 1}}


def test_unchanged_idle_pre_migration_build_is_allowed(recovery):
    recovery.require_build_only('build-new-api-image', state())


@pytest.mark.parametrize('field,value', [('pending_resets', 1), ('pg_major', 16),
                                        ('unresolved_wristbands', ['8004'])])
def test_other_business_conflicts_are_not_bypassed(recovery, field, value):
    current = state(); current[field] = value
    with pytest.raises(recovery.DeploymentError): recovery.require_build_only('build-new-api-image', current)


@pytest.mark.parametrize('phase', ['explicit-owner-schema-migration', 'publish-web', 'stop-api-writes'])
def test_never_cancels_build_after_a_different_phase(recovery, phase):
    with pytest.raises(recovery.DeploymentError): recovery.require_build_only(phase, state())


def test_migrated_schema_is_never_recovered_as_an_old_build(recovery):
    current = state()
    current['schema_revision'] = '20261004_catalog_packages'
    with pytest.raises(recovery.DeploymentError): recovery.require_build_only('build-new-api-image', current)


def test_unfinished_bill_blocks_build_recovery(recovery):
    current = state(); current['open_visits'] = 1
    with pytest.raises(recovery.DeploymentError): recovery.require_build_only('build-new-api-image', current)


def test_build_match_cannot_kill_another_build_or_process(recovery):
    image = 'xiquan-api:operations-56a4d0eeaf55'
    source = '/opt/xiquan-releases/operations-stage-' + 'a' * 32 + '/xiquan/server'
    assert recovery.exact_build(['/usr/bin/docker', 'build', '--tag', image, source], image, source)
    for args in [[], ['docker', 'run', image], ['docker', 'build', '--tag', image, '/other'],
                 ['docker', 'build', '--tag', 'other-image', source]]:
        assert not recovery.exact_build(args, image, source)


def test_reuse_requires_identical_requirements_and_real_pg17_tools(recovery):
    proof = {'requirements_sha256': 'a' * 64, 'python': [3, 12], 'compatible': True,
        'pg_dump': 'pg_dump (PostgreSQL) 17.11', 'pg_restore': 'pg_restore (PostgreSQL) 17.11'}
    recovery.require_dependencies(proof, 'a' * 64)
    for key, value in [('requirements_sha256', 'b' * 64), ('python', [3, 11]),
                       ('compatible', False), ('pg_dump', 'pg_dump (PostgreSQL) 16.4'),
                       ('pg_restore', None)]:
        changed = copy.deepcopy(proof); changed[key] = value
        with pytest.raises(recovery.DeploymentError): recovery.require_dependencies(changed, 'a' * 64)


def test_requirement_comparison_ignores_only_line_ending_variation(recovery):
    assert recovery.requirements_digest(b'Flask>=3.1,<4\r\nSQLAlchemy>=2,<3\r\n') == recovery.requirements_digest(b'Flask>=3.1,<4\nSQLAlchemy>=2,<3\n')
    assert recovery.requirements_digest(b'Flask>=3.1,<4\n') != recovery.requirements_digest(b'Flask>=3.0,<4\n')


def test_streaming_build_keeps_output_on_failure(recovery, tmp_path, capsys):
    log = tmp_path / 'build.log'
    with pytest.raises(recovery.DeploymentError):
        recovery.stream_build([sys.executable, '-c', 'print("visible layer",flush=True); raise SystemExit(2)'], log)
    assert 'visible layer' in capsys.readouterr().out
    assert 'visible layer' in log.read_text()


def test_streaming_build_refuses_to_overwrite_evidence(recovery, tmp_path):
    log = tmp_path / 'build.log'; log.write_text('existing evidence')
    with pytest.raises(recovery.DeploymentError):
        recovery.stream_build([sys.executable, '-c', 'print("new")'], log)
    assert log.read_text() == 'existing evidence'


def test_successful_streaming_build_preserves_real_child_output(recovery, tmp_path, capsys):
    log = tmp_path / 'build.log'
    recovery.stream_build([sys.executable, '-c', 'print("COPY cached packages only",flush=True)'], log)
    assert 'COPY cached packages only' in capsys.readouterr().out
    assert 'COPY cached packages only' in log.read_text()


def test_command_help_is_local_and_does_not_attempt_recovery():
    import subprocess
    result = subprocess.run([sys.executable, '-B', str(SCRIPT), '--help'], capture_output=True, text=True)
    assert result.returncode == 0
    assert '--stage' in result.stdout and '--job' in result.stdout
