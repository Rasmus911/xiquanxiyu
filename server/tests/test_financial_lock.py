from app.financial_lock import FINANCIAL_LOCK_KEY, lock_financial_writes
import pytest


def test_postgres_takes_transaction_lock_before_business_work():
    events = []
    class Dialect: name = 'postgresql'
    class Bind: dialect = Dialect()
    class Session:
        def get_bind(self): return Bind()
        def execute(self, sql, params): events.append((str(sql), params))
    lock_financial_writes(Session())
    assert events == [('SELECT pg_advisory_xact_lock(:key)', {'key': 713829418})]
    assert FINANCIAL_LOCK_KEY == 713829418


def test_sqlite_does_not_pretend_to_take_a_postgres_lock():
    class Dialect: name = 'sqlite'
    class Bind: dialect = Dialect()
    class Session:
        def get_bind(self): return Bind()
        def execute(self, *_): raise AssertionError('SQLite must not execute PG SQL')
    lock_financial_writes(Session())


def test_order_writer_takes_financial_lock_before_order_and_inventory_flush(client,admin_session,monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from app.models import CatalogItem, InventoryMovement, OrderItem, Wristband
    headers=admin_session['headers']
    band=Wristband.query.first()
    visit_id=client.post(f'/api/wristbands/{band.id}/open',headers=headers,json={}).get_json()['data']['id']
    product=CatalogItem.query.filter_by(kind='product',stock_tracked=True).first()
    events=[]
    monkeypatch.setattr('app.financial_lock.lock_financial_writes',lambda _session:events.append('lock'))
    def observed(session,_context,_instances):
        if any(isinstance(row,(OrderItem,InventoryMovement)) for row in session.new): events.append('flush')
    event.listen(Session,'before_flush',observed)
    try:
        response=client.post(f'/api/visits/{visit_id}/items/batch',headers=headers,
            json={'items':[{'catalog_item_id':product.id,'quantity':1}],'idempotency_key':'write-lock'})
        assert response.status_code==201
        assert events and events[0]=='lock'
        assert 'flush' in events
    finally: event.remove(Session,'before_flush',observed)


@pytest.mark.parametrize('method,path,body',[
    ('post','/api/inventory/adjust',{}),
    ('post','/api/members',{}),
    ('post','/api/checkout',{}),
    ('put','/api/settings/lost_wristband_fee',{}),
    ('post','/api/mobile/visits/missing/items',{}),
])
def test_invalid_financial_requests_are_serialized_before_business_lookup(client,admin_session,monkeypatch,method,path,body):
    events=[]
    monkeypatch.setattr('app.financial_lock.lock_financial_writes',lambda _session:events.append('lock'))
    response=getattr(client,method)(path,headers=admin_session['headers'],json=body)
    assert response.status_code in {400,403,404,409}
    assert events and events[0]=='lock'


def test_unauthorized_request_cannot_enter_money_lock(client,monkeypatch):
    events=[]
    monkeypatch.setattr('app.financial_lock.lock_financial_writes',lambda _session:events.append('lock'))
    response=client.post('/api/checkout',json={})
    assert response.status_code==401
    assert events==[]


def test_authenticated_scoped_staff_cannot_take_checkout_money_lock(client,strict_owner_session,monkeypatch):
    from app.auth_service import hash_password
    from app.extensions import db
    from app.models import Employee
    employee=Employee(username='lock-staff',display_name='隔离搓澡师',role='male_scrubber',
        password_hash=hash_password('fixture-password'),allowed_channels=['desktop'])
    db.session.add(employee); db.session.commit()
    login=client.post('/api/auth/login',json={'username':employee.username,'password':'fixture-password',
        'terminal_code':strict_owner_session['terminal_code'],'client_channel':'desktop'})
    assert login.status_code==200
    headers={'Authorization':'Bearer '+login.get_json()['data']['access_token'],
        'X-Business-Period':strict_owner_session['headers']['X-Business-Period']}
    events=[]
    monkeypatch.setattr('app.financial_lock.lock_financial_writes',lambda _session:events.append('lock'))
    response=client.post('/api/checkout',headers=headers,json={})
    assert response.status_code==403
    assert response.get_json()['error']['code']=='PERMISSION_DENIED'
    assert events==[]


@pytest.mark.parametrize('service',['catalog','compensation','inventory'])
def test_direct_money_services_lock_before_database_work(app,monkeypatch,service):
    from decimal import Decimal
    from app.models import CatalogItem
    from app.pricing_service import reprice_open_catalog_items,reprice_open_compensation_items
    from app.api.inventory import adjust_inventory_data
    events=[]
    monkeypatch.setattr('app.financial_lock.lock_financial_writes',lambda _session:events.append('lock'))
    catalog=CatalogItem.query.filter_by(kind='product').first()
    if service=='catalog': reprice_open_catalog_items(catalog)
    elif service=='compensation': reprice_open_compensation_items(Decimal(20))
    else:
        with pytest.raises(Exception): adjust_inventory_data(None,{'catalog_item_id':'missing'},None)
    assert events and events[0]=='lock'
