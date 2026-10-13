"""Replay PostgreSQL's SELECT FOR UPDATE privilege boundary at the ORM boundary."""
import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from test_inventory_excel055 import preview, apply
from test_independent_stock import post

@pytest.mark.parametrize('operation,status', [('complete',201),('cancel',200)])
def test_append_only_pending_rows_can_be_resolved_without_update_privilege(client,admin_session,operation,status):
    headers=admin_session['headers']
    body,plan=preview(client,headers,[dict(name='Read only pending proof',stock_quantity='800',package_cost='120')])
    assert apply(client,headers,body,plan).status_code==200
    pending=client.get('/api/inventory/excel/pending',headers=headers).get_json()['data'][0]
    observed=[]
    def read_only_boundary(execution):
        if execution.is_select and any(getattr(table,'name',None)=='stock_import_pending' for table in execution.statement.get_final_froms()):
            locked=getattr(execution.statement,'_for_update_arg',None) is not None
            observed.append(locked)
            if locked:
                raise PermissionError('SELECT FOR UPDATE needs UPDATE privilege on append-only evidence')
    event.listen(Session,'do_orm_execute',read_only_boundary)
    try:
        payload={'base_unit':'袋','package_unit':'箱','units_per_package':'200'} if operation=='complete' else {}
        result=post(client,headers,'/api/inventory/excel/pending/'+pending['id']+'/'+operation,payload,'resolve-read-only-'+operation)
        assert result.status_code==status,result.get_json()
        assert observed and not any(observed)
        assert client.get('/api/inventory/excel/pending',headers=headers).get_json()['data']==[]
    finally:
        event.remove(Session,'do_orm_execute',read_only_boundary)
