"""Cost basis belongs to the server, including password and rounding boundaries."""
from decimal import Decimal
import pytest
from app.extensions import db
from app.models import StockItem
from test_independent_stock import stock, post, balance


def patch(client, headers, row, body, key='cost055'):
    return client.patch('/api/inventory/stock-items/' + row['id'], headers={**headers, 'Idempotency-Key': key},
                        json={'version': row['version'], **body})


@pytest.mark.parametrize('basis,cost,package,base', [
    ('package', '120', '120.00', '0.600000'),
    ('base', '0.60', '120.00', '0.600000'),
    ('package', '1', '1.00', '0.005000'),
    ('base', '0', '0.00', '0.000000'),
])
def test_first_reference_cost_is_free_and_units_are_explicit(client, admin_session, basis, cost, package, base):
    h = admin_session['headers']; row = stock(client, h)
    response = patch(client, h, row, {'reference_cost': cost, 'cost_basis': basis})
    assert response.status_code == 200, response.get_json()
    value = response.get_json()['data']
    assert value['package_cost'] == package
    assert value['base_unit_cost'] == base
    assert value['cost_basis'] == basis


def test_changing_existing_package_cost_requires_own_password_before_mutation(client, admin_session):
    h = admin_session['headers']; row = stock(client, h)
    response = patch(client, h, row, {'reference_cost': '120', 'cost_basis': 'package'})
    assert response.status_code == 200
    row = response.get_json()['data']
    failed = patch(client, h, row, {'reference_cost': '130', 'cost_basis': 'package', 'name': '不可提交',
                                    'password': 'not-the-password'}, 'bad-password')
    assert failed.status_code in {400, 403}
    actual = balance(client, h, row['id'])
    assert actual['name'] == row['name'] and actual['package_cost'] == '120.00'
    success = patch(client, h, actual, {'reference_cost': '130', 'cost_basis': 'package', 'password': 'admin123'}, 'good-password')
    assert success.status_code == 200, success.get_json()
    assert success.get_json()['data']['base_unit_cost'] == '0.650000'


def test_legacy_base_reference_is_not_mistaken_for_box_cost(client, admin_session):
    h = admin_session['headers']; row = stock(client, h)
    response = patch(client, h, row, {'unit_cost': '0.60'})
    assert response.status_code == 200
    value = response.get_json()['data']
    assert value['package_cost'] == '120.00' and value['base_unit_cost'] == '0.600000'


def test_nondivisible_package_price_is_not_roundtripped_to_zero(client, admin_session):
    h = admin_session['headers']; row = stock(client, h, units_per_package='3')
    response = patch(client, h, row, {'reference_cost': '1.00', 'cost_basis': 'package'})
    assert response.status_code == 200
    row = response.get_json()['data']
    assert row['package_cost'] == '1.00' and row['base_unit_cost'] == '0.333333'
    assert db.session.get(StockItem, row['id']).reference_cost == Decimal('1.00')


@pytest.mark.parametrize('body', [
    {'reference_cost': '-1', 'cost_basis': 'package'},
    {'reference_cost': 'NaN', 'cost_basis': 'base'},
    {'reference_cost': '120'},
    {'reference_cost': '120', 'cost_basis': 'unknown'},
    {'reference_cost': '120', 'cost_basis': 'package', 'unit_cost': '1'},
])
def test_cost_rejects_conflicting_or_invalid_inputs(client, admin_session, body):
    h = admin_session['headers']; row = stock(client, h)
    assert patch(client, h, row, body).status_code == 400
