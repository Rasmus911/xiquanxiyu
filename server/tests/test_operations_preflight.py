"""Breaks caught: unreviewed ZIP contents and cloud writes before validation."""
import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'deploy/cloud/scripts/operations_preflight.py'


@pytest.fixture()
def preflight():
    assert SCRIPT.is_file(), 'Reviewed operations preflight entry point is missing'
    spec = importlib.util.spec_from_file_location('operations_preflight_fixture', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle(tmp_path, *, extra=None, wrong_hash=False, missing=False):
    files = {
        'server/app/operations_backup.py': b'reviewed backup fixture',
        'server/app/operations_upgrade.py': b'reviewed upgrade fixture',
        'server/app/catalog_defaults.py': b'reviewed catalog fixture',
        'server/app/__init__.py': b'reviewed initialization fixture',
        'server/Dockerfile': b'reviewed build fixture',
        'deploy/cloud/docker-compose.prod.yml': b'reviewed compose fixture',
        'client/dist/index.html': b'<html>desktop</html>',
        'mobile/dist/index.html': b'<html>mobile</html>',
        'deploy/cloud/.env.example': b'POSTGRES_PASSWORD=replace-me',
    }
    manifest = {'schema': 1, 'label': 'SOURCE/WEB', 'source_commit': 'a' * 40,
        'files': [{'file': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in files.items()]}
    if wrong_hash: manifest['files'][0]['sha256'] = '0' * 64
    if missing: files.pop('server/app/operations_backup.py')
    archive = tmp_path / 'xiquan-operations-SOURCE-WEB-fixture.zip'
    with zipfile.ZipFile(archive, 'w') as writer:
        for name, data in files.items(): writer.writestr('xiquan/' + name, data)
        writer.writestr('xiquan/source-manifest.json', json.dumps(manifest))
        writer.writestr('xiquan/SOURCE-WEB-NOT-PRODUCTION.txt', 'SOURCE/WEB fixture')
        if extra: writer.writestr(*extra)
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def test_archive_extracts_only_exact_manifest_after_complete_validation(preflight, tmp_path):
    archive, digest = bundle(tmp_path)
    stage = tmp_path / 'new-stage'
    result = preflight.stage_bundle(archive, digest, stage)
    assert result['source_commit'] == 'a' * 40
    assert (stage / 'xiquan/server/app/operations_backup.py').read_bytes() == b'reviewed backup fixture'
    assert not (stage / 'xiquan/.env').exists()


@pytest.mark.parametrize('name', ['xiquan/../outside', '/absolute', 'xiquan/.env',
    'xiquan/deploy/cloud/.env', 'xiquan/deploy/cloud/nginx/active.conf',
    'xiquan/deploy/cloud/updates/old.exe', 'xiquan/private/key.jks',
    'xiquan/server/app/extra.py', 'xiquan\\server\\app\\extra.py'])
def test_unsafe_or_unlisted_archive_never_creates_stage(preflight, tmp_path, name):
    archive, digest = bundle(tmp_path, extra=(name, b'not reviewed'))
    stage = tmp_path / 'new-stage'
    with pytest.raises(preflight.PreflightError): preflight.stage_bundle(archive, digest, stage)
    assert not stage.exists()


@pytest.mark.parametrize('problem', ['outer-sha', 'inner-sha', 'missing-file', 'duplicate'])
def test_archive_integrity_failures_leave_existing_project_untouched(preflight, tmp_path, problem):
    archive, digest = bundle(tmp_path, wrong_hash=problem == 'inner-sha', missing=problem == 'missing-file')
    if problem == 'outer-sha': digest = '0' * 64
    if problem == 'duplicate':
        with zipfile.ZipFile(archive, 'a') as writer:
            with pytest.warns(UserWarning, match='Duplicate'):
                writer.writestr('xiquan/source-manifest.json', '{}')
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    project = tmp_path / 'existing-project'
    project.mkdir()
    sentinel = project / '.env'
    sentinel.write_text('fixture-only-existing-configuration')
    stage = tmp_path / 'new-stage'
    with pytest.raises(preflight.PreflightError): preflight.stage_bundle(archive, digest, stage)
    assert sentinel.read_text() == 'fixture-only-existing-configuration'
    assert not stage.exists()


def test_existing_stage_is_not_reused_or_overwritten(preflight, tmp_path):
    archive, digest = bundle(tmp_path)
    stage = tmp_path / 'stage'
    stage.mkdir()
    (stage / 'sentinel').write_text('keep')
    with pytest.raises(preflight.PreflightError): preflight.stage_bundle(archive, digest, stage)
    assert (stage / 'sentinel').read_text() == 'keep'


def test_symlink_zip_entry_is_refused(preflight, tmp_path):
    archive, _digest = bundle(tmp_path)
    with zipfile.ZipFile(archive, 'a') as writer:
        entry = zipfile.ZipInfo('xiquan/link')
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        writer.writestr(entry, 'outside')
    with pytest.raises(preflight.PreflightError):
        preflight.stage_bundle(archive, hashlib.sha256(archive.read_bytes()).hexdigest(), tmp_path / 'stage')


def test_unimplemented_cutover_is_refused_before_any_cloud_operation(preflight, tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), '--mode', 'apply',
        '--bundle', str(tmp_path / 'absent.zip'), '--expected-sha256', '0' * 64], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'preflight' in result.stderr
    assert not list(tmp_path.iterdir())


def test_missing_private_configuration_is_reported_by_name_not_value(preflight, tmp_path):
    env = tmp_path / '.env'
    env.write_text('RUNTIME_DATABASE_URL=fixture-private-must-not-be-printed\n')
    with pytest.raises(preflight.PreflightError) as error:
        preflight.check_private_configuration(env)
    assert 'MAINTENANCE_DATABASE_URL' in str(error.value)
    assert 'fixture-private' not in str(error.value)


def test_local_archive_check_has_no_staging_or_cloud_side_effects(preflight, tmp_path):
    archive, digest = bundle(tmp_path)
    before = set(tmp_path.iterdir())
    result = subprocess.run([sys.executable, str(SCRIPT), '--local-check', '--bundle', str(archive),
        '--expected-sha256', digest], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data['source_commit'] == 'a' * 40
    assert data['stage_directory'] is None
    assert set(tmp_path.iterdir()) == before


def test_psql_command_tags_cannot_break_read_only_json_protocol(preflight, monkeypatch):
    # Docker is unavailable locally. Replace only the subprocess boundary with
    # psql's two distinct documented stdout forms, not the parser under test.
    def run(argv, **_kwargs):
        shell = argv[-3]
        class Result:
            stdout = '{"pg_major":17,"audit_rows":285}' if ' -q ' in shell else 'BEGIN\n{"pg_major":17}\nROLLBACK\n'
        return Result()
    monkeypatch.setattr(preflight.subprocess, 'run', run)
    assert preflight.query_cloud_state() == {'pg_major': 17, 'audit_rows': 285}
