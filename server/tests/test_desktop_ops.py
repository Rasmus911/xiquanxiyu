"""Desktop management operations exercise real API and financial rows."""
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import CatalogItem, Employee, Member, MemberPass, Visit, Wristband


def role_session(client, owner, role):
    response = client.post('/api/employees', headers=owner['headers'], json={
        'username': 'ops-' + role, 'display_name': role, 'role': role,
        'password': 'ops-password-2026', 'allowed_channels': ['desktop']})
    assert response.status_code == 201
    login = client.post('/api/auth/login', json={'username': 'ops-' + role,
        'password': 'ops-password-2026', 'terminal_code': 'ENTRY-TEST',
        'client_channel': 'desktop'}).get_json()['data']
    return {'Authorization': 'Bearer ' + login['access_token'],
        'X-Business-Period': login['business_state']['period_id']}, login


@pytest.mark.parametrize('role', ['cashier', 'inventory', 'manager'])
def test_management_capabilities_and_all_catalog_kinds(client, strict_owner_session, role):
    headers, login = role_session(client, strict_owner_session, role)
    caps = login['business_state']['capabilities']
    assert all(caps.get(key) for key in ('visit_clear', 'member_delete', 'catalog_delete', 'catalog_write'))
    ticket = CatalogItem.query.filter_by(kind='ticket').first()
    response = client.patch('/api/catalog/' + ticket.id, headers=headers, json={'price': '13.00'})
    assert response.status_code == 200
    assert response.get_json()['data']['can_edit'] is True
    if role != 'manager':
        assert client.post('/api/checkout/unknown/refund', headers=headers, json={}).status_code == 403


def test_member_archive_retains_row_requires_own_password(client, strict_owner_session):
    headers, _ = role_session(client, strict_owner_session, 'cashier')
    member = Member(phone='13800001001', balance=0)
    db.session.add(member); db.session.commit()
    path = '/api/members/' + member.id
    assert client.delete(path, headers=headers, json={'password': strict_owner_session['password']}).status_code == 403
    assert member.is_active
    assert client.delete(path, headers=headers, json={'password': 'ops-password-2026'}).status_code == 200
    assert db.session.get(Member, member.id).deleted_at is not None
    assert client.get(path, headers=headers).status_code == 404
    assert client.get('/api/members', headers=headers).get_json()['data'] == []
    assert client.delete(path, headers=headers, json={'password': 'ops-password-2026'}).status_code == 200


@pytest.mark.parametrize('guard', ['positive', 'negative', 'expired_pass', 'open_visit', 'settling_visit'])
def test_member_archive_preserves_financial_rights(client, strict_owner_session, guard):
    member = Member(phone='13800001002', balance=Decimal('1') if guard == 'positive' else Decimal('-1') if guard == 'negative' else 0)
    db.session.add(member); db.session.flush()
    if guard == 'expired_pass':
        from datetime import date
        db.session.add(MemberPass(member_id=member.id, name='expired', remaining_count=1,
            is_active=False, valid_until=date(2000, 1, 1)))
    if guard.endswith('visit'):
        db.session.add(Visit(member_id=member.id, wristband_id=Wristband.query.first().id,
            opened_by_id=strict_owner_session['owner_id'], status='settling' if guard.startswith('settling') else 'open'))
    db.session.commit()
    response = client.delete('/api/members/' + member.id, headers=strict_owner_session['headers'],
        json={'password': strict_owner_session['password']})
    assert response.status_code == 409
    assert member.is_active


def test_catalog_archive_blocks_reactivation_preserves_inventory(client, strict_owner_session):
    item = CatalogItem(kind='product', name='archive me', price=5, stock_tracked=True, stock_quantity=7)
    db.session.add(item); db.session.commit()
    headers = strict_owner_session['headers']; path = '/api/catalog/' + item.id
    assert client.delete(path, headers=headers, json={'password': strict_owner_session['password']}).status_code == 200
    assert item.stock_quantity == 7
    assert item.deleted_at is not None
    assert item.id not in [row['id'] for row in client.get('/api/catalog?active=false', headers=headers).get_json()['data']]
    assert client.patch(path, headers=headers, json={'is_active': True}).status_code == 404
    assert client.delete(path, headers=headers, json={'password': strict_owner_session['password']}).status_code == 200


def test_cashier_clear_only_selected_linked_visit(client, strict_owner_session):
    headers, _ = role_session(client, strict_owner_session, 'cashier')
    bands = Wristband.query.order_by(Wristband.number).limit(2).all()
    visits = []
    for band in bands:
        band.status = 'in_use'
        visits.append(Visit(wristband_id=band.id, opened_by_id=strict_owner_session['owner_id'], party_id='test-party'))
    db.session.add_all(visits); db.session.commit()
    path = '/api/wristbands/' + bands[0].id + '/force-clear'
    assert client.post(path, headers=headers, json={'password': 'wrong', 'reason': 'test'}).status_code == 403
    assert visits[0].status == 'open'
    assert client.post(path, headers=headers, json={'password': 'ops-password-2026', 'reason': 'test'}).status_code == 200
    assert bands[0].status == 'available'
    assert bands[1].status == 'in_use'
    assert visits[1].status == 'open'


def test_staff_lost_live_visit_visible_and_denied_management(client, strict_owner_session):
    headers, _ = role_session(client, strict_owner_session, 'male_scrubber')
    band = Wristband.query.filter_by(number='001').first() or Wristband.query.order_by(Wristband.number).first()
    band.status = 'lost'
    db.session.add(Visit(wristband_id=band.id, opened_by_id=strict_owner_session['owner_id']))
    db.session.commit()
    rows = client.get('/api/wristbands', headers=headers).get_json()['data']
    assert [row['id'] for row in rows] == [band.id]
    assert client.get('/api/wristbands?status=available', headers=headers).get_json()['data'] == []
    for path in ('/api/members/unknown', '/api/catalog/unknown'):
        assert client.delete(path, headers=headers, json={'password': 'ops-password-2026'}).status_code == 403
    assert client.post('/api/wristbands/' + band.id + '/force-clear', headers=headers,
        json={'password': 'ops-password-2026', 'reason': 'test'}).status_code == 403


def test_archived_catalog_cannot_be_new_package_dependency(client, strict_owner_session):
    ticket = CatalogItem.query.filter_by(kind='ticket').first()
    item = CatalogItem(kind='service', name='old', price=1)
    db.session.add(item); db.session.commit()
    headers = strict_owner_session['headers']
    assert client.delete('/api/catalog/' + item.id, headers=headers,
        json={'password': strict_owner_session['password']}).status_code == 200
    definition = {'schema': 1, 'display_contents': ['test'], 'slots': [
        {'catalog_item_ids': [ticket.id], 'quantity': '1'},
        {'catalog_item_ids': [item.id], 'quantity': '1'}]}
    response = client.post('/api/catalog', headers=headers,
        json={'kind': 'package', 'name': 'invalid', 'price': '1', 'package_definition': definition})
    assert response.status_code == 400


def test_member_tombstone_cannot_start_visit(client, strict_owner_session):
    member = Member(phone='13800001003', balance=0)
    db.session.add(member); db.session.commit()
    headers = strict_owner_session['headers']
    client.delete('/api/members/' + member.id, headers=headers,
        json={'password': strict_owner_session['password']})
    band = Wristband.query.first()
    response = client.post('/api/wristbands/' + band.id + '/open', headers=headers,
        json={'member_id': member.id})
    assert response.status_code == 404


def test_catalog_archive_guards_package_and_unsettled_references(client, strict_owner_session):
    from app.models import OrderItem
    ticket = CatalogItem.query.filter_by(kind='ticket').first()
    item = CatalogItem(kind='service', name='included', price=10)
    db.session.add(item); db.session.flush()
    definition = {'schema': 1, 'display_contents': ['test'], 'slots': [
        {'catalog_item_ids': [ticket.id], 'quantity': '1'},
        {'catalog_item_ids': [item.id], 'quantity': '1'}]}
    package = CatalogItem(kind='package', name='package', price=10, package_definition=definition)
    db.session.add(package); db.session.commit()
    headers = strict_owner_session['headers']; payload = {'password': strict_owner_session['password']}
    assert client.delete('/api/catalog/' + item.id, headers=headers, json=payload).status_code == 409
    package.package_definition = {'schema': 1, 'display_contents': ['ticket'],
        'slots': [{'catalog_item_ids': [ticket.id], 'quantity': '1'}]}
    visit = Visit(wristband_id=Wristband.query.first().id, opened_by_id=strict_owner_session['owner_id'])
    db.session.add(visit); db.session.flush()
    line = OrderItem(visit_id=visit.id, catalog_item_id=package.id, kind='package', name_snapshot='package',
        unit_price=10, quantity=1, total_amount=10, created_by_id=strict_owner_session['owner_id'], package_snapshot=definition)
    db.session.add(line); db.session.commit()
    assert client.delete('/api/catalog/' + item.id, headers=headers, json=payload).status_code == 409
    assert item.is_active
