"""Authenticated transaction tests: inventory is reconciled, never blindly replaced."""
import base64
import hashlib
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import StockItem, StockMovement
from app.inventory_xlsx import export_inventory_xlsx
from test_independent_stock import stock, post, balance


def file_body(rows):
    raw = export_inventory_xlsx(rows)
    return dict(source_base64=base64.b64encode(raw).decode(), source_sha256=hashlib.sha256(raw).hexdigest())


def preview(client, headers, rows):
    body = file_body(rows)
    response = client.post('/api/inventory/excel/preview', headers=headers, json=body)
    assert response.status_code == 200, response.get_json()
    return body, response.get_json()['data']


def apply(client, headers, body, plan, confirmed=(), key='excel055', **extra):
    return post(client, headers, '/api/inventory/excel/apply',
        {**body, 'preview_token': plan['preview_token'], 'confirmed_rows': list(confirmed), **extra}, key)


@pytest.mark.parametrize('target,needs_confirm', [('600.000', True), ('600.001', False), ('0', True), ('900', False)])
def test_exact25percent_preview_requires_confirmation_before_writing(client, admin_session, target, needs_confirm):
    h = admin_session['headers']; row = stock(client, h)
    body, plan = preview(client, h, [dict(name=row['name'], stock_quantity=target, package_cost=None)])
    change = plan['rows'][0]
    assert change['requires_consumption_confirmation'] is needs_confirm
    assert balance(client, h, row['id'])['stock_quantity'] == '800.000'
    response = apply(client, h, body, plan)
    if needs_confirm:
        assert response.status_code == 400
        response = apply(client, h, body, plan, [change['row_number']], key='confirmed055')
    assert response.status_code == 200, response.get_json()
    assert Decimal(balance(client, h, row['id'])['stock_quantity']) == Decimal(target)


def test_preview_changed_concurrently_is_rejected_without_overwrite(client, admin_session):
    h = admin_session['headers']; row = stock(client, h)
    body, plan = preview(client, h, [dict(name=row['name'], stock_quantity='600', package_cost=None)])
    post(client, h, '/api/inventory/stock-adjust', dict(stock_item_id=row['id'], version=row['version'],
        movement_type='purchase', quantity='100', input_unit='base', reason='采购入库'), 'other-clerk')
    response = apply(client, h, body, plan, [3])
    assert response.status_code == 409
    assert balance(client, h, row['id'])['stock_quantity'] == '900.000'


def test_new_rows_wait_for_units_then_complete_once(client, admin_session):
    h = admin_session['headers']; count = StockItem.query.count()
    body, plan = preview(client, h, [dict(name='全新牛奶', stock_quantity='800', package_cost='120')])
    response = apply(client, h, body, plan)
    assert response.status_code == 200
    assert StockItem.query.count() == count
    pending = client.get('/api/inventory/excel/pending', headers=h).get_json()['data']
    assert len(pending) == 1 and pending[0]['quantity'] == '800.000'
    path = '/api/inventory/excel/pending/' + pending[0]['id'] + '/complete'
    result = post(client, h, path, {'base_unit': '袋', 'package_unit': '箱', 'units_per_package': '200'}, 'complete-new')
    assert result.status_code == 201, result.get_json()
    row = result.get_json()['data']
    assert row['stock_quantity'] == '800.000' and row['package_cost'] == '120.00'
    assert row['base_unit_cost'] == '0.600000'
    assert post(client, h, path, {'base_unit': '袋', 'package_unit': '箱', 'units_per_package': '200'}, 'complete-new').status_code == 201
    assert client.get('/api/inventory/excel/pending', headers=h).get_json()['data'] == []
    assert StockItem.query.count() == count + 1


def test_existing_cost_update_authenticates_before_any_batch_mutation(client, admin_session):
    h = admin_session['headers']; row = stock(client, h)
    first = client.patch('/api/inventory/stock-items/' + row['id'], headers={**h, 'Idempotency-Key': 'first-cost'},
        json={'version': row['version'], 'reference_cost': '120', 'cost_basis': 'package'}).get_json()['data']
    body, plan = preview(client, h, [dict(name=row['name'], stock_quantity='700', package_cost='130'),
                                  dict(name='不能偷建的新品', stock_quantity='10', package_cost='5')])
    response = apply(client, h, body, plan, password='wrong')
    assert response.status_code == 403
    assert balance(client, h, row['id'])['stock_quantity'] == '800.000'
    assert client.get('/api/inventory/excel/pending', headers=h).get_json()['data'] == []
    response = apply(client, h, body, plan, key='right-password', password='admin123')
    assert response.status_code == 200, response.get_json()
    assert balance(client, h, row['id'])['package_cost'] == '130.00'


def test_duplicate_rows_block_whole_file_and_omissions_do_not_delete(client, admin_session):
    h = admin_session['headers']; row = stock(client, h)
    body, plan = preview(client, h, [dict(name=row['name'], stock_quantity='600'),
                                  dict(name=row['name'], stock_quantity='500')])
    assert plan['errors']
    assert apply(client, h, body, plan, [3, 4]).status_code == 400
    assert balance(client, h, row['id'])['stock_quantity'] == '800.000'


def test_replay_does_not_duplicate_stocktake_and_unknown_id_never_falls_back(client, admin_session):
    h = admin_session['headers']; row = stock(client, h)
    body, plan = preview(client, h, [dict(name=row['name'], stock_quantity='700')])
    first = apply(client, h, body, plan)
    assert first.status_code == 200
    assert apply(client, h, body, plan).get_json()['data'] == first.get_json()['data']
    assert StockMovement.query.filter_by(stock_item_id=row['id'], movement_type='adjust').count() == 1
    body, plan = preview(client, h, [dict(name=row['name'], stock_quantity='100', id='missing', version=1)])
    assert plan['errors'] and apply(client, h, body, plan, [3], key='unknown-id').status_code == 400


def test_export_is_real_xlsx_and_mapping_tamper_is_rejected(client, admin_session):
    from app.inventory_xlsx import parse_inventory_xlsx
    h = admin_session['headers']; row = stock(client, h)
    response = client.get('/api/inventory/excel/export', headers=h)
    assert response.status_code == 200
    parsed = parse_inventory_xlsx(response.data)
    exported = next(item for item in parsed if item['stock_item_id'] == row['id'])
    assert exported['mapping_token'] and exported['quantity'] == '800'
    body, plan = preview(client, h, [dict(name=row['name'], stock_quantity='700', id=row['id'],
        version=exported['source_version'], mapping_token='changed')])
    assert plan['errors'] and apply(client, h, body, plan, key='tamper').status_code == 400


def test_excel_endpoints_do_not_grant_access_to_ordering_staff(client, admin_session, desktop050_employee_session, strict_owner_session):
    employee = desktop050_employee_session(role='male_scrubber')
    h = employee['headers']
    assert client.get('/api/inventory/excel/export', headers=h).status_code == 403
    assert client.get('/api/inventory/excel/pending', headers=h).status_code == 403


def test_legacy_unknown_units_wait_then_update_original_identity_with_confirmation(client, admin_session):
    h = admin_session['headers']; row = stock(client, h)
    master = db.session.get(StockItem, row['id']); master.base_unit = '原销售单位'; db.session.commit()
    body, plan = preview(client, h, [dict(name=row['name'], stock_quantity='600', package_cost='120')])
    assert not plan['errors']
    assert plan['rows'][0]['action'] == 'needs_units'
    assert plan['rows'][0]['requires_consumption_confirmation']
    assert apply(client, h, body, plan, [3]).status_code == 200
    assert balance(client, h, row['id'])['stock_quantity'] == '800.000'
    pending = client.get('/api/inventory/excel/pending', headers=h).get_json()['data'][0]
    assert pending['target_stock_item_id'] == row['id']
    path = '/api/inventory/excel/pending/' + pending['id'] + '/complete'
    count = StockItem.query.count()
    result = post(client, h, path, {'base_unit':'袋','package_unit':'箱','units_per_package':'200'}, 'complete-legacy')
    assert result.status_code == 200, result.get_json()
    after = result.get_json()['data']
    assert after['id'] == row['id'] and after['stock_quantity'] == '600.000'
    assert after['package_cost'] == '120.00' and after['base_unit_cost'] == '0.600000'
    assert StockItem.query.count() == count


def test_legacy_pending_cannot_overwrite_an_intervening_stock_change(client, admin_session):
    h = admin_session['headers']; row = stock(client, h)
    master = db.session.get(StockItem, row['id']); master.base_unit = '原销售单位'; db.session.commit()
    body, plan = preview(client, h, [dict(name=row['name'], stock_quantity='700')])
    assert apply(client, h, body, plan).status_code == 200
    pending = client.get('/api/inventory/excel/pending', headers=h).get_json()['data'][0]
    post(client,h,'/api/inventory/stock-adjust',dict(stock_item_id=row['id'],version=row['version'],
        movement_type='purchase',quantity='100',input_unit='base',reason='采购入库'),'intervening')
    result = post(client,h,'/api/inventory/excel/pending/'+pending['id']+'/complete',
        {'base_unit':'袋','package_unit':'箱','units_per_package':'200'},'stale-pending')
    assert result.status_code == 409
    assert balance(client,h,row['id'])['stock_quantity'] == '900.000'


def test_pending_conversion_cannot_change_existing_box_cost_without_own_password(client, admin_session):
    h=admin_session['headers'];row=stock(client,h,units_per_package='1')
    master=db.session.get(StockItem,row['id']);master.base_unit='原销售单位';master.reference_cost=120;master.cost_basis='package';master.unit_cost=120;db.session.commit()
    body,plan=preview(client,h,[dict(name=row['name'],stock_quantity='800')])
    assert apply(client,h,body,plan).status_code==200
    pending=client.get('/api/inventory/excel/pending',headers=h).get_json()['data'][0]
    assert pending['requires_password']
    path='/api/inventory/excel/pending/'+pending['id']+'/complete'
    fields={'base_unit':'袋','package_unit':'箱','units_per_package':'200'}
    assert post(client,h,path,fields,'without-password').status_code==403
    assert balance(client,h,row['id'])['base_unit']=='原销售单位'
    result=post(client,h,path,{**fields,'password':'admin123'},'with-password')
    assert result.status_code==200 and result.get_json()['data']['base_unit_cost']=='0.600000'
