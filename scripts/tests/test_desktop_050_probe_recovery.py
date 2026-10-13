import importlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy/cloud/scripts'))


def test_exact_repair_matches_both_actual_fixed_sources():
    repair = importlib.import_module('desktop_050_probe_recovery')
    for name in repair.FIXED_FILES:
        old = subprocess.check_output(['git', 'show', repair.BASE_COMMIT + ':' + name], cwd=ROOT)
        assert repair.expected_fixed_source(name, old) == (ROOT / name).read_bytes().replace(b'\r\n', b'\n')
    with pytest.raises(ValueError):
        repair.expected_fixed_source('server/app/auth_service.py', b'unchanged')


def test_adoption_rejects_unrelated_runtime_changes(tmp_path):
    repair = importlib.import_module('desktop_050_probe_recovery')
    old = tmp_path / 'old'
    new = tmp_path / 'new'
    old.mkdir()
    new.mkdir()
    old_manifest = {'files': [{'file': 'client/src/changed.ts', 'sha256': 'before'}]}
    new_manifest = {'files': [{'file': 'client/src/changed.ts', 'sha256': 'after'}] +
                             [{'file': name, 'sha256': 'added'} for name in repair.ADDED_FILES]}
    with pytest.raises(ValueError, match='existing SOURCE change'):
        repair.validate_source_delta(old, new, old_manifest, new_manifest)


def test_install_retains_existing_checkpoint_instead_of_exclusive_overwrite(tmp_path, monkeypatch):
    import hashlib
    import json
    deploy = importlib.import_module('desktop_050_deploy')
    cloud = tmp_path / 'cloud'
    cloud.mkdir()
    job = tmp_path / 'job'
    job.mkdir()
    (cloud / 'docker-compose.prod.yml').write_bytes(b'old-compose')
    previous = {'owner': 'owner', 'compose_sha256': hashlib.sha256(b'old-compose').hexdigest()}
    (job / 'context.json').write_text(json.dumps(previous))
    driver = deploy.Desktop050.__new__(deploy.Desktop050)
    driver.job = job
    driver.context = dict(previous)
    driver.context_file_sha256 = deploy.digest_file(job / 'context.json')
    driver.manifest = {'files': [{'file': 'deploy/cloud/docker-compose.prod.yml',
                                'sha256': hashlib.sha256(b'new-compose').hexdigest()}]}
    driver.copy = lambda record, target, mode: target.write_bytes(b'new-compose')
    monkeypatch.setattr(deploy, 'CLOUD', cloud)
    monkeypatch.setattr(deploy.Stock, 'install', lambda self: None)
    driver.install()
    current = json.loads((job / 'context.json').read_text())
    assert current['compose_sha256'] == hashlib.sha256(b'new-compose').hexdigest()
    assert current['owner'] == 'owner'
    retained = list(job.glob('context-retained-*.json'))
    assert len(retained) == 1
    assert json.loads(retained[0].read_text()) == previous


def test_context_update_rejects_a_changed_checkpoint(tmp_path):
    deploy = importlib.import_module('desktop_050_deploy')
    path = tmp_path / 'context.json'
    path.write_text('{"owner":"original"}')
    expected = deploy.digest_file(path)
    path.write_text('{"owner":"another-job"}')
    with pytest.raises(deploy.DeploymentError, match='changed'):
        deploy.replace_context(path, {'owner': 'new'}, expected)
    assert path.read_text() == '{"owner":"another-job"}'
    assert list(tmp_path.glob('context-retained-*.json')) == []


def test_same_context_is_idempotent_without_duplicate_evidence(tmp_path):
    deploy = importlib.import_module('desktop_050_deploy')
    path = tmp_path / 'context.json'
    path.write_text('{"owner":"original"}')
    digest = deploy.digest_file(path)
    assert deploy.replace_context(path, {'owner': 'original'}, digest) == digest
    assert list(tmp_path.glob('context-retained-*.json')) == []
