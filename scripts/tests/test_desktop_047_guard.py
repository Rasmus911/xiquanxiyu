import copy
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'deploy/cloud/scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'server'))
import desktop_047_guard as guard

def fixture():
    before={'tables':{name:{'rows':1,'sha256':'same','columns':{'id':'VARCHAR'}} for name in
        ['members','stock_items','catalog_items','audit_logs','alembic_version','business_state']},
        'roles':'same','owners':{'members':'owner'},'audit_valid':True,
        'alerts_expected':{'s':'120.000'},'alerts_actual':{'s':'1.000'},'schema':guard.OLD}
    after=copy.deepcopy(before);after['schema']=guard.HEAD;after['alerts_actual']={'s':'120.000'}
    after['tables'].update(stock_costs={'rows':0},schema_upgrade_markers={'rows':1})
    after['owners'].update(stock_costs='owner',schema_upgrade_markers='owner')
    after['markers']=['20261007_insights_cost']
    return before,after

def test_additive_guard_retains_all_old_rows_and_allows_only_exact_alerts():
    before,after=fixture();guard.compare(before,after)
    for name in before['tables']:
        changed=copy.deepcopy(after);changed['tables'][name]['sha256']='modified'
        with pytest.raises(guard.GuardError):guard.compare(before,changed)
    for field in ['roles','audit_valid','alerts_actual']:
        changed=copy.deepcopy(after);changed[field]=None
        with pytest.raises(guard.GuardError):guard.compare(before,changed)
    changed=copy.deepcopy(after);changed['tables']['stock_costs']['rows']=1
    with pytest.raises(guard.GuardError):guard.compare(before,changed)
    changed=copy.deepcopy(after);changed['tables']['unknown']={}
    with pytest.raises(guard.GuardError):guard.compare(before,changed)
