import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'deploy/cloud/scripts'))
import desktop_046_guard as guard


def test_code_only_update_rejects_any_business_schema_or_authority_change():
    original = {'tables': {name:{'rows':1,'sha256':'fixture','columns':{'id':'VARCHAR'}}
        for name in ['members','catalog_items','stock_items','audit_logs','alembic_version']},
        'roles':'unchanged','owners':{'members':'owner'},'audit_valid':True}
    guard.compare(original,copy.deepcopy(original))
    for name in original['tables']:
        changed = copy.deepcopy(original); changed['tables'][name]['sha256'] = 'different'
        with pytest.raises(guard.GuardError): guard.compare(original,changed)
    changed = copy.deepcopy(original); changed['roles'] = 'different'
    with pytest.raises(guard.GuardError): guard.compare(original,changed)

