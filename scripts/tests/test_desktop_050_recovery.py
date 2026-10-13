import importlib
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'deploy/cloud/scripts'),str(ROOT/'server')]
def test_resources_budget_measured_concurrent_peak_not_arbitrary_two_gib():
    deploy=importlib.import_module('desktop_050_deploy')
    assert deploy.resource_budget(758*1024**2,7*1024**3,restore=True)['required_memory_mib']==640
    with pytest.raises(Exception):deploy.resource_budget(639*1024**2,7*1024**3,restore=True)
def test_partial_after_snapshot_is_preserved_and_replaced_with_fresh_attempt(tmp_path):
    deploy=importlib.import_module('desktop_050_deploy')
    folder=tmp_path/'after';folder.mkdir();(folder/'database.backup').write_bytes(b'')
    retained=deploy.retain_partial_backup(folder)
    assert (retained/'database.backup').exists() and not folder.exists()
    assert retained.parent==tmp_path
def test_completed_backup_is_never_renamed(tmp_path):
    deploy=importlib.import_module('desktop_050_deploy')
    folder=tmp_path/'after';folder.mkdir();(folder/'receipt.json').write_text('{}')
    with pytest.raises(Exception):deploy.retain_partial_backup(folder)
