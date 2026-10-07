"""Reset acceptance against a strict UUID policy and disposable SQLite files."""
from decimal import Decimal

import pytest

from app import create_app
from app.access_policy import activate_policy
from app.auth_service import hash_password
from app.config import TestConfig
from app.extensions import db
from app.models import Employee, Member, StoredValueLedger, Terminal
from legacy_seed import seed_legacy_defaults as seed_defaults


@pytest.fixture()
def reset_app(tmp_path):
    class ResetConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'reset.sqlite').as_posix()}"
        ACCESS_POLICY_LEGACY_COMPAT = False
        RESET_WORKER_ENABLED = False
        RESET_PRIVATE_DIR = str(tmp_path / 'private')
    application = create_app(ResetConfig)
    with application.app_context():
        db.create_all()
        seed_defaults()
        digest = hash_password('original-password')
        people = [Employee(username=name, display_name=name, role='admin', password_hash=digest)
                  for name in ('owner', 'mobile1', 'mobile2')]
        db.session.add_all([*people, Terminal(code='RESET-TEST', name='test')])
        db.session.commit()
        activate_policy(people[0].id, [row.id for row in people[1:]])
        member = Member(phone='13800000001', balance=Decimal('30.00'))
        db.session.add(member)
        db.session.flush()
        db.session.add(StoredValueLedger(member_id=member.id, amount=30, balance_after=30,
            entry_type='recharge', payment_method='cash', operator_id=people[0].id))
        db.session.commit()
        yield application
        db.session.remove()
        db.engine.dispose()


def session(client, username='owner', channel='desktop'):
    response = client.post('/api/auth/login', json={'username': username,
        'password': 'original-password', 'terminal_code': 'RESET-TEST', 'client_channel': channel})
    assert response.status_code == 200
    data = response.get_json()['data']
    return {'Authorization': f"Bearer {data['access_token']}",
            'X-Business-Period': data['business_state']['period_id']}


def payload(preview, **changes):
    return {'username': 'owner', 'password': 'original-password',
            'confirmation': '重置当前经营数据', 'confirmation_token': preview['confirmation_token'],
            'idempotency_key': 'reset-acceptance-001', **changes}


def test_only_owner_can_preview_reset(reset_app):
    client = reset_app.test_client()
    response = client.get('/api/business/reset/preview', headers=session(client, 'mobile1', 'mobile'))
    assert response.status_code == 403
    assert response.get_json()['error']['code'] == 'OWNER_REQUIRED'


def test_reset_preview_shows_real_stored_balance(reset_app):
    client = reset_app.test_client()
    response = client.get('/api/business/reset/preview', headers=session(client))
    assert response.status_code == 200
    assert response.get_json()['data']['summary']['stored_balance'] == '30.00'
    assert response.get_json()['data']['summary']['stock_preserved'] is True


def test_creation_reauth_confirmation_and_persistent_idempotency(reset_app):
    from app.models import ResetTaskModel
    client = reset_app.test_client()
    headers = session(client)
    preview_response = client.get('/api/business/reset/preview', headers=headers)
    assert preview_response.status_code == 200
    preview = preview_response.get_json()['data']
    for change, status, code in [({'password': 'wrong'}, 403, 'REAUTH_FAILED'),
                                ({'confirmation': 'yes'}, 400, 'RESET_CONFIRMATION_INVALID')]:
        response = client.post('/api/business/reset/tasks', headers=headers, json=payload(preview, **change))
        assert response.status_code == status
        assert response.get_json()['error']['code'] == code
    response = client.post('/api/business/reset/tasks', headers=headers, json=payload(preview))
    assert response.status_code == 202
    task = response.get_json()['data']
    repeat = client.post('/api/business/reset/tasks', headers=headers, json=payload(preview))
    assert repeat.status_code == 202
    assert repeat.get_json()['data']['id'] == task['id']
    stored = db.session.get(ResetTaskModel, task['id'])
    assert 'password' not in str(stored.context) and 'confirmation_token' not in str(stored.context)
    assert client.get('/api/business/reset/tasks?idempotency_key=reset-acceptance-001',
                      headers=headers).get_json()['data'][0]['id'] == task['id']


def test_preview_rejects_revision_and_session_change(reset_app):
    client = reset_app.test_client()
    headers = session(client)
    response = client.get('/api/business/reset/preview', headers=headers)
    assert response.status_code == 200
    preview = response.get_json()['data']
    other = session(client)
    assert client.post('/api/business/reset/tasks', headers=other,
                       json=payload(preview)).status_code == 400
    db.session.add(Member(phone='13800000002', balance=0))
    db.session.commit()
    response = client.post('/api/business/reset/tasks', headers=headers, json=payload(preview))
    assert response.status_code == 409
    assert response.get_json()['error']['code'] == 'RESET_PREVIEW_STALE'


def queued_task(client):
    headers = session(client)
    preview = client.get('/api/business/reset/preview', headers=headers).get_json()['data']
    response = client.post('/api/business/reset/tasks', headers=headers, json=payload(preview))
    assert response.status_code == 202
    return headers, response.get_json()['data']['id']


def test_worker_archives_money_preserves_stock_and_revokes_sessions(reset_app):
    from app import reset_service
    from app.audit_service import verify_audit_chain
    from app.business_period import archive_read
    from app.models import (
        BusinessStateModel,
        CatalogItem,
        InventoryMovement,
        ResetEventModel,
        ResetTaskModel,
        Visit,
        Wristband,
    )
    owner = Employee.query.filter_by(username='owner').one()
    band = Wristband.query.first()
    band.status = 'occupied'
    band.note = 'old note'
    db.session.add(Visit(wristband_id=band.id, opened_by_id=owner.id))
    item = CatalogItem.query.filter_by(kind='product').first()
    item.stock_tracked = True
    item.stock_quantity = 7
    db.session.commit()
    item_id, band_id, item_version = item.id, band.id, item.version
    old_period = db.session.get(BusinessStateModel, 1).period_id
    client = reset_app.test_client()
    stock_headers = session(client)
    independent = client.post('/api/inventory/stock-items', headers={**stock_headers,'Idempotency-Key':'reset-stock'},
        json={'name':'独立耗材','base_unit':'袋','package_unit':'箱','units_per_package':'20',
            'package_spec':'20袋每箱','opening_quantity':'800'}).get_json()['data']
    db.session.add(InventoryMovement(catalog_item_id=item_id, movement_type='purchase', quantity=7,
        balance_after=7, operator_id=owner.id, note='preserved evidence'))
    db.session.commit()
    headers, task_id = queued_task(client)
    reset_service.run_reset_task(task_id)
    db.session.expire_all()
    task = db.session.get(ResetTaskModel, task_id)
    assert task.status == 'completed'
    assert task.new_period_id != old_period
    assert Member.query.count() == 0
    assert Visit.query.count() == 0
    assert db.session.get(CatalogItem, item_id).stock_quantity == 7
    assert db.session.get(CatalogItem, item_id).version == item_version
    from app.models import StockItem, StockMovement
    assert db.session.get(StockItem, independent['id']).stock_quantity == 800
    master = db.session.get(StockItem, independent['id'])
    assert (master.version, master.package_unit, master.units_per_package, master.package_spec) == (
        independent['version'], '箱', 20, '20袋每箱')
    assert db.session.get(Wristband, band_id).status == 'available'
    assert db.session.get(Wristband, band_id).note is None
    with archive_read(old_period):
        assert StockMovement.query.filter_by(reference_id=task_id).count() == 0
        assert StockMovement.query.filter_by(stock_item_id=independent['id']).one().quantity == 800
        assert Member.query.one().balance == Decimal('30.00')
        assert Visit.query.one().status == 'reset_closed'
        assert InventoryMovement.query.filter_by(reference_id=task_id).count() == 0
    assert ResetEventModel.query.filter_by(reset_id=task_id).count() == 1
    assert verify_audit_chain() == (True, None)
    assert client.get('/api/business/state', headers=headers).status_code in (401, 409)
    fresh = session(client)
    movements = client.get('/api/inventory/stock-movements', headers=fresh).get_json()['data']
    assert len(movements) == 1
    assert movements[0]['quantity'] == '800.000'
    legacy = client.get('/api/inventory/movements', headers=fresh).get_json()['data']
    assert len(legacy) == 1 and legacy[0]['quantity'] == '7.000'
    response = client.post('/api/inventory/stock-adjust', headers={**fresh, 'Idempotency-Key': 'new-period-stock'},
        json={'stock_item_id': independent['id'], 'version': independent['version'],
            'movement_type': 'purchase', 'quantity': '1', 'input_unit': 'base', 'reason': 'new-period'})
    assert response.status_code == 200
    movements = client.get('/api/inventory/stock-movements', headers=fresh).get_json()['data']
    assert sorted(row['quantity'] for row in movements) == ['1.000', '800.000']
    response = client.get(f'/api/business/reset/tasks/{task_id}', headers=fresh)
    assert response.status_code == 200
    assert set(response.get_json()['data']['backup']) == {'sha256', 'size'}
    archives = client.get('/api/business/archives', headers=fresh)
    assert archives.status_code == 200
    assert archives.get_json()['data'][0]['period_id'] == old_period
    assert archives.get_json()['data'][0]['summary']['stored_balance'] == '30.00'
    evidence = client.get(f'/api/business/archives/{old_period}/evidence?table=members', headers=fresh)
    assert evidence.status_code == 200
    assert evidence.get_json()['data']['rows'][0]['balance'] == '30.00'
    audit = client.get(f'/api/business/archives/{old_period}/evidence?table=audit_logs', headers=fresh)
    assert audit.status_code == 200
    assert any(row['action'] == 'business.reset' for row in audit.get_json()['data']['rows'])
    from app.financial_integrity import check_financial_integrity
    assert check_financial_integrity()['valid'] is True
    assert check_financial_integrity(old_period)['valid'] is True


def test_worker_is_independent_of_request_and_recovers_completed_task(reset_app):
    import threading
    import time

    from app.models import ResetTaskModel
    from app.reset_service import recover_reset_tasks
    reset_app.config['RESET_WORKER_ENABLED'] = True
    client = reset_app.test_client()
    _, task_id = queued_task(client)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        db.session.remove()
        task = db.session.get(ResetTaskModel, task_id)
        if task.status in {'completed', 'failed'}:
            break
        db.session.remove()
        time.sleep(0.02)
    assert task.status == 'completed'
    db.session.remove()
    for worker in threading.enumerate():
        if worker.name == f'reset-{task_id}':
            worker.join(timeout=10)
            assert not worker.is_alive()
    recover_reset_tasks()
    assert db.session.get(ResetTaskModel, task_id).status == 'completed'


def test_lost_reset_response_can_be_found_after_relogin(reset_app):
    from app.reset_service import run_reset_task
    client = reset_app.test_client()
    headers = session(client)
    preview = client.get('/api/business/reset/preview', headers=headers).get_json()['data']
    original = payload(preview)
    response = client.post('/api/business/reset/tasks', headers=headers, json=original)
    task_id = response.get_json()['data']['id']
    run_reset_task(task_id)
    fresh = session(client)
    found = client.get('/api/business/reset/tasks?idempotency_key=reset-acceptance-001', headers=fresh)
    assert found.status_code == 200 and found.get_json()['data'][0]['id'] == task_id
    retried = client.post('/api/business/reset/tasks', headers=fresh, json=original)
    assert retried.status_code == 202 and retried.get_json()['data']['id'] == task_id


def test_maintenance_rejects_auth_terminal_and_direct_sql(reset_app):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.models import BusinessStateModel
    client = reset_app.test_client()
    headers = session(client)
    state = db.session.get(BusinessStateModel, 1)
    state.maintenance = True
    db.session.commit()
    for path, body in [('/api/auth/login', {'username': 'owner', 'password': 'original-password'}),
                       ('/api/terminals/register', {'code': 'new', 'name': 'new'}),
                       ('/api/auth/logout', {})]:
        response = client.post(path, headers=headers, json=body)
        assert response.status_code == 503
        assert response.get_json()['error']['code'] == 'BUSINESS_MAINTENANCE'
    with pytest.raises(DBAPIError, match='BUSINESS_MAINTENANCE'):
        with db.engine.begin() as connection:
            connection.execute(text("UPDATE catalog_items SET stock_quantity=99"))


def test_financial_keys_isolate_channel_actor_period_and_payload_conflicts(reset_app):
    from app.models import CatalogItem, InventoryMovement
    from app.reset_service import run_reset_task
    client = reset_app.test_client()
    owner = session(client)
    mobile = session(client, channel='mobile')
    other = session(client, 'mobile1', 'mobile')
    item = CatalogItem.query.filter_by(kind='product').first()
    item.stock_tracked = True
    item.stock_quantity = 0
    item_id = item.id
    db.session.commit()
    body = {'catalog_item_id': item_id, 'quantity': 2, 'movement_type': 'purchase',
            'idempotency_key': 'same-client-key'}
    for headers in (owner, mobile, other):
        response = client.post('/api/inventory/adjust', headers=headers, json=body)
        assert response.status_code == 200
        retry = client.post('/api/inventory/adjust', headers=headers, json=body)
        assert retry.status_code == 200
        changed = client.post('/api/inventory/adjust', headers=headers, json={**body, 'quantity': 3})
        assert changed.status_code == 409
        assert changed.get_json()['error']['code'] == 'IDEMPOTENCY_CONFLICT'
    assert db.session.get(CatalogItem, item_id).stock_quantity == 6
    assert InventoryMovement.query.count() == 3
    _, task_id = queued_task(client)
    run_reset_task(task_id)
    fresh = session(client)
    assert client.post('/api/inventory/adjust', headers=fresh, json=body).status_code == 200
    assert db.session.get(CatalogItem, item_id).stock_quantity == 8
    assert InventoryMovement.query.count() == 1


def test_failed_backup_does_not_change_period_or_money(reset_app):
    from app.models import BusinessStateModel, ResetTaskModel
    from app.reset_service import run_reset_task
    client = reset_app.test_client()
    headers, task_id = queued_task(client)
    reset_app.config['RESET_PRIVATE_DIR'] = ''  # A real invalid backup destination.
    run_reset_task(task_id)
    state = db.session.get(BusinessStateModel, 1)
    assert state.period_id == headers['X-Business-Period'] and not state.maintenance
    assert Member.query.one().balance == Decimal('30.00')
    assert db.session.get(ResetTaskModel, task_id).error_code == 'RESET_BACKUP_FAILED'


def test_recovery_never_replays_unexecuted_task_and_retains_conflicting_maintenance(reset_app):
    from sqlalchemy import update

    from app.models import BusinessStateModel, ResetTaskModel
    from app.reset_service import recover_reset_tasks
    client = reset_app.test_client()
    _, task_id = queued_task(client)
    recover_reset_tasks()
    assert db.session.get(ResetTaskModel, task_id).status == 'failed'
    assert Member.query.one().balance == Decimal('30.00')
    db.session.remove()
    with db.engine.begin() as connection:
        connection.execute(update(ResetTaskModel).where(ResetTaskModel.id == task_id).values(
            status='resetting', new_period_id='contradictory-period'))
    with pytest.raises(RuntimeError, match='Conflicting'):
        recover_reset_tasks()
    assert db.session.get(BusinessStateModel, 1).maintenance is True


def test_worker_revalidates_revision_and_forged_task_proof(reset_app):
    from sqlalchemy import update

    from app.models import ResetTaskModel
    from app.reset_service import run_reset_task
    client = reset_app.test_client()
    _, task_id = queued_task(client)
    db.session.add(Member(phone='13800000003', balance=12))
    db.session.commit()
    run_reset_task(task_id)
    assert db.session.get(ResetTaskModel, task_id).error_code == 'RESET_PREVIEW_STALE'
    db.session.remove()
    with db.engine.begin() as connection:
        connection.execute(update(ResetTaskModel).where(ResetTaskModel.id == task_id).values(
            status='queued', context={'proof': {'owner_id': 'forged'}, 'signature': 'forged'}))
    run_reset_task(task_id)
    assert db.session.get(ResetTaskModel, task_id).error_code == 'RESET_CONFIRMATION_INVALID'


def test_two_queued_tasks_cannot_reset_twice(reset_app):
    from app.models import BusinessPeriod, ResetTaskModel
    from app.reset_service import run_reset_task
    client = reset_app.test_client()
    headers = session(client)
    preview = client.get('/api/business/reset/preview', headers=headers).get_json()['data']
    ids = [client.post('/api/business/reset/tasks', headers=headers,
                       json=payload(preview, idempotency_key=f'queued-task-{i}')).get_json()['data']['id']
           for i in range(2)]
    run_reset_task(ids[0])
    run_reset_task(ids[1])
    assert BusinessPeriod.query.count() == 2
    assert db.session.get(ResetTaskModel, ids[0]).status == 'completed'
    assert db.session.get(ResetTaskModel, ids[1]).status == 'failed'


def test_backup_restoration_recovery_does_not_reexecute(reset_app, tmp_path):
    import shutil

    from app.models import BusinessStateModel, ResetTaskModel
    from app.reset_service import recover_reset_tasks, run_reset_task
    client = reset_app.test_client()
    headers, task_id = queued_task(client)
    run_reset_task(task_id)
    task = db.session.get(ResetTaskModel, task_id)
    restored_path = tmp_path / 'restored.sqlite'
    shutil.copy2(task.backup['private_path'], restored_path)
    class RestoredConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f'sqlite:///{restored_path.as_posix()}'
        RESET_PRIVATE_DIR = str(tmp_path / 'restored-private')
        ACCESS_POLICY_LEGACY_COMPAT = False
    restored_app = create_app(RestoredConfig)
    with restored_app.app_context():
        recover_reset_tasks()
        assert db.session.get(BusinessStateModel, 1).period_id == headers['X-Business-Period']
        assert not db.session.get(BusinessStateModel, 1).maintenance
        assert db.session.get(ResetTaskModel, task_id).status == 'failed'
        assert Member.query.one().balance == Decimal('30.00')
        db.session.remove()
        db.engine.dispose()


def test_invalidated_connection_stops_worker_until_recovery(reset_app, monkeypatch):
    from app import reset_backup
    from app.models import BusinessStateModel, ResetTaskModel
    from app.reset_service import recover_reset_tasks, run_reset_task
    client = reset_app.test_client()
    _, task_id = queued_task(client)
    original = reset_backup.create_database_backup
    def disconnect(connection, *args):
        original(connection, *args)  # Perform a genuine full backup first.
        connection.invalidate()
        raise ConnectionError('test physical connection interrupted')
    monkeypatch.setattr(reset_backup, 'create_database_backup', disconnect)
    with pytest.raises(ConnectionError, match='physical connection'):
        run_reset_task(task_id)
    assert db.session.get(BusinessStateModel, 1).maintenance
    assert db.session.get(ResetTaskModel, task_id).status == 'backing_up'
    with pytest.raises(RuntimeError, match='requires explicit recovery'):
        run_reset_task(task_id)
    assert db.session.get(BusinessStateModel, 1).maintenance
    recover_reset_tasks()
    assert not db.session.get(BusinessStateModel, 1).maintenance
    assert db.session.get(ResetTaskModel, task_id).status == 'failed'
    assert Member.query.one().balance == Decimal('30.00')


def test_expired_preview_and_sensitive_password_lockout(reset_app, monkeypatch):
    import time

    from app.models import ResetTaskModel
    client = reset_app.test_client()
    headers = session(client)
    now = time.time()
    with monkeypatch.context() as patcher:
        patcher.setattr('itsdangerous.timed.time.time', lambda: now - 301)
        old = client.get('/api/business/reset/preview', headers=headers).get_json()['data']
    response = client.post('/api/business/reset/tasks', headers=headers, json=payload(old))
    assert response.status_code == 400
    assert response.get_json()['error']['code'] == 'RESET_CONFIRMATION_INVALID'
    preview = client.get('/api/business/reset/preview', headers=headers).get_json()['data']
    for _ in range(5):
        assert client.post('/api/business/reset/tasks', headers=headers,
                           json=payload(preview, password='bad')).status_code == 403
    assert client.post('/api/business/reset/tasks', headers=headers, json=payload(preview)).status_code == 423
    assert ResetTaskModel.query.count() == 0


def test_recovery_rejects_completed_result_when_current_period_is_old(reset_app):
    from sqlalchemy import update

    from app.models import BusinessStateModel
    from app.reset_service import recover_reset_tasks, run_reset_task
    client = reset_app.test_client()
    headers, task_id = queued_task(client)
    run_reset_task(task_id)
    db.session.remove()
    with db.engine.begin() as connection:
        connection.execute(update(BusinessStateModel).where(BusinessStateModel.id == 1).values(
            period_id=headers['X-Business-Period']))
    with pytest.raises(RuntimeError, match='Conflicting'):
        recover_reset_tasks()
    assert db.session.get(BusinessStateModel, 1).maintenance


def test_runtime_upgrade_adds_maintenance_ownership_without_reset(tmp_path):
    from pathlib import Path

    from flask_migrate import upgrade
    from sqlalchemy import inspect, text

    from app.schema_maintenance import ensure_runtime_schema
    class UpgradeConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'old-schema.sqlite').as_posix()}"
    application = create_app(UpgradeConfig)
    with application.app_context():
        upgrade(directory=str(Path(__file__).resolve().parents[1] / 'migrations'),
                revision='20261002_business_period_reset')
        with db.engine.begin() as connection:
            # Reconstruct the pre-task-3 structural schema, whose guards did not
            # yet reference maintenance_reset_id.
            triggers = connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' "
                                               "AND name LIKE 'barrier_%'")).scalars().all()
            for name in triggers:
                connection.exec_driver_sql(f'DROP TRIGGER "{name}"')
            connection.execute(text('ALTER TABLE business_state DROP COLUMN maintenance_reset_id'))
            before = connection.execute(text('SELECT period_id,business_revision FROM business_state')).one()
        ensure_runtime_schema()
        assert 'maintenance_reset_id' in {column['name'] for column in inspect(db.engine).get_columns('business_state')}
        with db.engine.connect() as connection:
            assert connection.execute(text('SELECT period_id,business_revision FROM business_state')).one() == before
        db.session.remove()
        db.engine.dispose()


def test_worker_imports_maintenance_denial_spool_after_commit(reset_app, monkeypatch):
    from pathlib import Path

    from app import reset_backup
    from app.audit_service import verify_audit_chain
    from app.models import AuditLog
    from app.reset_service import run_reset_task
    client = reset_app.test_client()
    _, task_id = queued_task(client)
    original = reset_backup.create_database_backup
    def request_during_backup(connection, *args):
        with reset_app.app_context():
            response = client.post('/api/terminals/register', json={'code': 'DURING-RESET', 'name': 'blocked'},
                                   headers={'X-Request-ID': 'denied-during-reset'})
            assert response.status_code == 503
        return original(connection, *args)
    monkeypatch.setattr(reset_backup, 'create_database_backup', request_during_backup)
    run_reset_task(task_id)
    db.session.expire_all()
    event = AuditLog.query.filter_by(request_id='denied-during-reset').one()
    assert event.entity_type == 'security_spool'
    assert event.context['path'] == '/api/terminals/register'
    assert not list((Path(reset_app.config['RESET_PRIVATE_DIR']) / 'spool').glob('*.json'))
    assert verify_audit_chain() == (True, None)


def test_barrier_invalidates_on_rollback_failure_and_releases_file_lock(reset_app):
    from sqlalchemy import event

    from app.business_barrier import control_connection, exclusive_barrier
    with control_connection() as connection:
        def interrupted_rollback(_connection):
            raise RuntimeError('injected rollback failure')
        with pytest.raises(RuntimeError, match='rollback failure'):
            with exclusive_barrier(connection, 'rollback-test'):
                connection.exec_driver_sql('SELECT 1')
                event.listen(connection, 'rollback', interrupted_rollback)
        assert connection.invalidated
    with control_connection() as replacement:
        with exclusive_barrier(replacement, 'replacement'):
            assert replacement.exec_driver_sql('SELECT 1').scalar_one() == 1


@pytest.mark.parametrize('pause_at', ['after_auth', 'between_reads'])
@pytest.mark.parametrize('explicit_snapshot', [False, True])
def test_authenticated_get_cannot_cross_cutover(reset_app, monkeypatch, pause_at, explicit_snapshot):
    import threading

    from flask import request
    from sqlalchemy import event

    from app import auth_service
    from app.models import BusinessStateModel, MemberPass, ResetTaskModel
    from app.reset_service import run_reset_task
    member = Member.query.one()
    db.session.add(MemberPass(member_id=member.id, name='old pass', remaining_count=4))
    db.session.commit()
    client = reset_app.test_client()
    headers, task_id = queued_task(client)
    db.session.remove()
    # WAL permits a genuine SQLite read snapshot to overlap the real worker's
    # committed cutover; legacy sqlite3 SELECT-only requests have no such snapshot.
    with db.engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA journal_mode=WAL').scalar_one() == 'wal'
    request_thread = threading.get_ident()
    completed = []
    observed_periods = []

    def cutover():
        def work():
            with reset_app.app_context():
                run_reset_task(task_id)
                assert db.session.get(ResetTaskModel, task_id).status == 'completed'
                db.session.add(Member(phone='13900000099', name='new-period-secret', balance=0))
                db.session.commit()
                completed.append(db.session.get(BusinessStateModel, 1).period_id)
                db.session.remove()
        worker = threading.Thread(target=work)
        worker.start()
        worker.join(timeout=20)
        assert not worker.is_alive() and len(completed) == 1
        assert completed[0] != headers['X-Business-Period']

    original_auth = auth_service.current_employee
    def authenticate_then_pause():
        employee = original_auth()
        if request.path == '/api/members' and not completed:
            if explicit_snapshot:
                connection = db.session.connection()
                connection.exec_driver_sql('BEGIN')
                connection.exec_driver_sql('SELECT period_id FROM business_state').one()
            if pause_at == 'after_auth':
                cutover()
        return employee
    monkeypatch.setattr(auth_service, 'current_employee', authenticate_then_pause)

    def before_query(_connection, _cursor, statement, parameters, _context, _many):
        if threading.get_ident() != request_thread or not statement.lstrip().upper().startswith('SELECT'):
            return
        if 'FROM member_passes' in statement and pause_at == 'between_reads' and not completed:
            cutover()
        if 'FROM members' in statement or 'FROM member_passes' in statement:
            observed_periods.append(parameters)
    event.listen(db.engine, 'before_cursor_execute', before_query)
    try:
        response = client.get('/api/members', headers=headers)
    finally:
        event.remove(db.engine, 'before_cursor_execute', before_query)
    assert response.status_code == 409
    assert response.get_json()['error']['code'] == 'BUSINESS_PERIOD_CHANGED'
    assert 'new-period-secret' not in response.get_data(as_text=True)
    assert 'data' not in response.get_json()
    assert observed_periods and all(headers['X-Business-Period'] in params for params in observed_periods)
    # Request-local binding must not poison the next, freshly authenticated GET.
    fresh = client.get('/api/members', headers=session(client))
    assert fresh.status_code == 200
    assert fresh.get_json()['data'][0]['name'] == 'new-period-secret'


def test_health_and_authorized_task_reads_remain_available_during_maintenance(reset_app):
    from app.models import BusinessStateModel
    client = reset_app.test_client()
    headers, task_id = queued_task(client)
    state = db.session.get(BusinessStateModel, 1)
    state.maintenance = True
    state.maintenance_reset_id = task_id
    db.session.commit()
    assert client.get('/api/health').status_code == 200
    assert client.get('/api/business/state', headers=headers).status_code == 200
    assert client.get('/api/business/reset/tasks', headers=headers).status_code == 200
    assert client.get(f'/api/business/reset/tasks/{task_id}', headers=headers).status_code == 200


def test_recovery_completed_without_result_keeps_maintenance(reset_app):
    from sqlalchemy import update

    from app.models import BusinessStateModel, ResetTaskModel
    from app.reset_service import recover_reset_tasks
    client = reset_app.test_client()
    headers, task_id = queued_task(client)
    db.session.remove()
    with db.engine.begin() as connection:
        connection.execute(update(ResetTaskModel).where(ResetTaskModel.id == task_id).values(status='completed'))
        connection.execute(update(BusinessStateModel).where(BusinessStateModel.id == 1).values(
            maintenance=True, maintenance_reset_id=task_id))
    with pytest.raises(RuntimeError, match='Conflicting reset evidence'):
        recover_reset_tasks()
    state = db.session.get(BusinessStateModel, 1)
    assert state.maintenance and state.maintenance_reset_id == task_id
    assert state.period_id == headers['X-Business-Period']
    assert db.session.get(ResetTaskModel, task_id).status == 'completed'
