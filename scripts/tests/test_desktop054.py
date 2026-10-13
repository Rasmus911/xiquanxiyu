"""Release invariants; real PostgreSQL rehearsal is a separate cloud gate."""
import importlib
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deploy/cloud/scripts'))


def driver():
    return importlib.import_module('desktop_054_deploy')


def test_release_identity_and_resources():
    api = driver()
    assert api.OLD == '20261012_physical_membership'
    assert api.HEAD == '20261013_wristband_chip'
    assert api.TARGETS == ['win10-x86', 'win10-x64', 'win11-x86', 'win11-x64']
    assert api.resource_budget(700*1024**2, 7*1024**3, restore=True)['required_memory_mib'] == 640
    with pytest.raises(api.DeploymentError):
        api.resource_budget(639*1024**2, 7*1024**3, restore=True)


def test_guard_projects_all_existing_business_columns():
    guard = importlib.import_module('desktop_054_guard')
    assert guard.NEW == {'wristband_chip_bindings', 'wristband_scan_sessions'}
    assert guard.row_projection('members') == 'to_jsonb(t)'
    assert guard.row_projection('stock_items') == 'to_jsonb(t)'
    assert guard.row_projection('alembic_version') == "to_jsonb(t) - 'version_num'"


def test_backup_diagnostic_path_is_inside_private_subdirectory():
    source = Path(driver().__file__).read_text(encoding='utf-8')
    assert "self.job / 'backup-diagnostics'" in source
    assert 'path.relative_to(self.job).as_posix()' in source
    assert "'app/' if r['file'].startswith('client/')" in source
    assert "'--http1.1'" in source
    assert 'desktop_054_pgproof.py' in source


def test_checkpoint_refuses_migration_replay(tmp_path):
    api=driver()
    cp=api.Checkpoints(tmp_path, {'job':'fixture'})
    with pytest.raises(api.DeploymentError, match='do not replay DDL'):
        cp.classify(api.HEAD, True, 'fixture')


def test_new_cloud_invocation_supports_all_and_version_contract():
    root=Path(__file__).resolve().parents[2]
    source=(root/'scripts/invoke-desktop-054.ps1').read_text(encoding='utf-8-sig')
    assert "'all'" in source.split('$Mode')[0]
    assert "'0.5.4'" in source and "'1.2.11'" in source
    assert '20261013_wristband_chip' in source
    assert 'desktop054-stage-' in source and 'desktop054-cutover-' in source
