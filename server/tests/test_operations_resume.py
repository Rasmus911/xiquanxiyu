"""Resume guards exercise real checks; Docker/SSH are never used in these tests."""
import copy
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'deploy/cloud/scripts/operations_resume.py'


@pytest.fixture
def resume(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('operations_resume_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def image_fixture():
    context = {'source_commit': 'a' * 40, 'old_api_image': 'sha256:' + 'b' * 64}
    image = {'Id': 'sha256:' + 'c' * 64,
        'Config': {'Labels': {'org.opencontainers.image.revision': 'a' * 40},
                   'User': 'xiquan', 'WorkingDir': '/app',
                   'Entrypoint': ['/app/docker-entrypoint.sh'], 'Cmd': ['python', 'run.py']}}
    receipt = {'status': 'offline_image_verified', 'source_commit': 'a' * 40,
        'image_id': image['Id'], 'base_image_id': context['old_api_image'],
        'requirements_sha256': 'd' * 64, 'production_unchanged': True,
        'api_started': False, 'migration_performed': False,
        'pg_dump': 'pg_dump (PostgreSQL) 17.11', 'pg_restore': 'pg_restore (PostgreSQL) 17.11'}
    proof = {'requirements_sha256': 'd' * 64, 'python': [3, 12], 'compatible': True,
        'pg_dump': receipt['pg_dump'], 'pg_restore': receipt['pg_restore'],
        'payload': {'app/__init__.py': 'e' * 64}}
    return receipt, context, image, proof


def test_only_the_actual_verified_image_and_payload_are_reused(resume):
    receipt, context, image, proof = image_fixture()
    resume.require_verified_image(receipt, context, image, proof, 'd' * 64, {'app/__init__.py': 'e' * 64})
    for key, value in [('status', 'built-only'), ('source_commit', 'f' * 40),
                       ('image_id', 'sha256:' + 'f' * 64), ('base_image_id', 'other'),
                       ('production_unchanged', False), ('api_started', True),
                       ('migration_performed', True), ('requirements_sha256', 'f' * 64)]:
        changed = dict(receipt); changed[key] = value
        with pytest.raises(resume.DeploymentError):
            resume.require_verified_image(changed, context, image, proof, 'd' * 64, {'app/__init__.py': 'e' * 64})
    changed = copy.deepcopy(proof); changed['payload']['app/__init__.py'] = 'f' * 64
    with pytest.raises(resume.DeploymentError):
        resume.require_verified_image(receipt, context, image, changed, 'd' * 64, {'app/__init__.py': 'e' * 64})
    changed = copy.deepcopy(image); changed['Config']['Entrypoint'] = ['/other']
    with pytest.raises(resume.DeploymentError):
        resume.require_verified_image(receipt, context, changed, proof, 'd' * 64, {'app/__init__.py': 'e' * 64})


@pytest.mark.parametrize('artifact', ['rehearsal.env', 'isolated-role-login.sql', 'rehearsal',
    'rehearsal-verified.json', 'owner-check', 'post-migration', 'prepared.json', 'completed.json'])
def test_partial_or_completed_jobs_are_never_blindly_repeated(resume, tmp_path, artifact):
    resume.require_pristine_checkpoint('build-new-api-image-offline-verified', tmp_path)
    (tmp_path / artifact).touch()
    with pytest.raises(resume.DeploymentError):
        resume.require_pristine_checkpoint('build-new-api-image-offline-verified', tmp_path)


def test_wrong_checkpoint_cannot_authorize_migration(resume, tmp_path):
    for phase in ['build-new-api-image', 'explicit-owner-schema-migration', 'completed-cloud-cutover']:
        with pytest.raises(resume.DeploymentError): resume.require_pristine_checkpoint(phase, tmp_path)


def test_private_environment_parser_rejects_duplicates_without_echoing_values(resume):
    assert resume.parse_environment('POSTGRES_USER=operations_restore\nVALUE=a=b\n') == {
        'POSTGRES_USER': 'operations_restore', 'VALUE': 'a=b'}
    for content in ['SECRET_KEY=fixture-only\nSECRET_KEY=other\n', 'bad=fixture-only\n',
                    'SECRET_KEY=fixture-only\x00\n', 'export SECRET_KEY=fixture-only\n']:
        with pytest.raises(resume.DeploymentError) as error: resume.parse_environment(content)
        assert 'fixture-only' not in str(error.value)


def clone_fixture():
    name = 'xiquan-operations-restore-' + 'a' * 32
    context = {'postgres_image': 'sha256:' + 'b' * 64, 'network': 'xiquan_database'}
    verified = {'restore_container': name, 'restore_volume': name + '-data'}
    variables = {'POSTGRES_USER': 'operations_restore', 'POSTGRES_DB': 'operations_restore',
                 'POSTGRES_PASSWORD': 'fixture-password-only'}
    info = {'Name': '/' + name, 'Image': context['postgres_image'],
        'State': {'Running': True, 'Health': {'Status': 'healthy'}},
        'Config': {'Labels': {'xiquan.operations.restore': name},
                   'Env': [key + '=' + value for key, value in variables.items()]},
        'HostConfig': {'PortBindings': {}}, 'NetworkSettings': {'Networks': {context['network']: {}}},
        'Mounts': [{'Type': 'volume', 'Name': name + '-data', 'Destination': '/var/lib/postgresql/data'}]}
    return info, context, verified, variables


def test_rehearsal_requires_the_original_private_healthy_clone(resume):
    info, context, verified, variables = clone_fixture()
    resume.require_isolated_clone(info, context, verified, variables)
    mutations = [lambda v: v.update(Image='other'), lambda v: v['State'].update(Running=False),
        lambda v: v['HostConfig'].update(PortBindings={'5432/tcp': [{'HostPort': '5432'}]}),
        lambda v: v['NetworkSettings']['Networks'].update(public={}),
        lambda v: v['Mounts'][0].update(Name='production-volume'),
        lambda v: v['Config']['Labels'].update({'xiquan.operations.restore': 'other'}),
        lambda v: v['Config'].update(Env=['POSTGRES_PASSWORD=other'])]
    for mutate in mutations:
        changed = copy.deepcopy(info); mutate(changed)
        with pytest.raises(resume.DeploymentError):
            resume.require_isolated_clone(changed, context, verified, variables)
    changed = dict(variables); changed['POSTGRES_DB'] = 'production'
    with pytest.raises(resume.DeploymentError): resume.require_isolated_clone(info, context, verified, changed)


def test_resume_runs_rehearsal_before_ddl_and_never_builds_or_applies(resume):
    actions = []
    class Operations:
        def rehearsal(self): actions.append('rehearsal')
        def migrate(self): actions.append('migrate')
        def snapshot_restore(self): actions.append('restore')
        def preview(self): actions.append('preview'); return {'can_apply': True}
        def save_preview(self, preview): actions.append('saved')
    resume.resume_remaining(Operations())
    assert actions == ['rehearsal', 'migrate', 'restore', 'preview', 'saved']


def test_failed_rehearsal_prevents_production_ddl(resume):
    class Operations:
        migrated = False
        def rehearsal(self): raise resume.DeploymentError('isolated verification failed')
        def migrate(self): self.migrated = True
    operations = Operations()
    with pytest.raises(resume.DeploymentError): resume.resume_remaining(operations)
    assert not operations.migrated
