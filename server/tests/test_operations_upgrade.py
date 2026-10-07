"""Only isolated file databases, with explicit legacy seeds; no cloud connections."""
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app import create_app
from app.audit_service import verify_audit_chain, write_audit
from app.config import TestConfig
from app.extensions import db
from app.models import (AuditLog, BusinessStateModel, CatalogItem, Employee, Member,
    OrderItem, ResetTaskModel, SystemSetting, Visit, Wristband)


@pytest.fixture()
def legacy_app(tmp_path):
    class Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'legacy.sqlite').as_posix()}"
        RESET_PRIVATE_DIR = str(tmp_path / 'private')
    app = create_app(Config)
    with app.app_context():
        db.create_all()
        from legacy_seed import seed_legacy_defaults
        seed_legacy_defaults()
        employee = Employee(username='original-owner', display_name='原用户', role='admin', password_hash='opaque')
        db.session.add(employee)
        db.session.flush()
        water = CatalogItem.query.filter_by(name='矿泉水').one()
        water.stock_quantity = Decimal(5)
        towel = CatalogItem.query.filter_by(name='一次性搓澡巾').one()
        towel.stock_quantity = Decimal(8)
        member = Member(phone='13800000001', balance=25)
        band = Wristband.query.filter_by(number='8001').one()
        visit = Visit(wristband_id=band.id, opened_by_id=employee.id)
        db.session.add_all([member, visit]); db.session.flush()
        line = OrderItem(visit_id=visit.id, catalog_item_id=water.id, kind='product', name_snapshot='矿泉水',
            unit_price=3, quantity=1, total_amount=3, created_by_id=employee.id)
        db.session.add(line); db.session.flush()
        visit.status = 'closed'
        write_audit('fixture.original', 'visit', visit.id, {'amount':'3.00'})
        db.session.commit()
        yield app, dict(employee_id=employee.id, band_id=band.id, visit_id=visit.id, line_id=line.id,
            water_id=water.id, towel_id=towel.id, member_id=member.id)
        db.session.remove(); db.engine.dispose()


@pytest.mark.parametrize('blocking', ['open','settling','lost','reset','number','towel'])
def test_preview_blocks_unsafe_cutover_without_writing(legacy_app, blocking):
    from app.operations_upgrade import preview_upgrade
    _, ids = legacy_app
    if blocking in {'open','settling'}:
        db.session.add(Visit(wristband_id=ids['band_id'], opened_by_id=ids['employee_id'], status=blocking))
    elif blocking == 'lost': db.session.get(Wristband, ids['band_id']).status = 'lost'
    elif blocking == 'reset':
        db.session.add(ResetTaskModel(idempotency_key='pending', owner_id=ids['employee_id'],
            old_period_id=db.session.get(BusinessStateModel, 1).period_id, status='queued'))
    elif blocking == 'number': db.session.add(Wristband(number='001', bath_area='male'))
    else: db.session.add(CatalogItem(kind='product', name='澡巾', price=6))
    db.session.commit()
    before = db.session.get(BusinessStateModel, 1).business_revision
    result = preview_upgrade(db.session)
    assert result['can_apply'] is False
    assert result['conflicts']
    if blocking in {'open','settling','lost'}: assert ids['band_id'] in result['blocking_wristband_ids']
    assert Wristband.query.filter_by(number='002').count() == 0
    assert db.session.get(BusinessStateModel, 1).business_revision == before


def test_cutover_preserves_history_stock_money_and_is_repeat_safe(legacy_app, monkeypatch):
    from app.operations_upgrade import apply_upgrade, preview_upgrade, preview_digest, verify_upgrade
    from app.seed import seed_defaults
    _, ids = legacy_app
    original_audit = AuditLog.query.first().current_hash
    preview = preview_upgrade(db.session)
    assert preview['can_apply'] is True
    assert preview['retained_products'][ids['water_id']]['stock_quantity'] == '5.000'
    digest = preview_digest(preview)
    db.session.rollback()
    # Actual dump/restore is an external dependency verified independently in R3.
    # Stub only its receipt gate here; all database mutations and barriers are real.
    monkeypatch.setattr('app.operations_backup.validate_backup_receipt', lambda *_args: {})
    with db.engine.connect() as connection:
        result = apply_upgrade(connection, digest, 'unused-test-receipt')
    db.session.expire_all()
    assert result['applied'] is True
    assert verify_upgrade(db.session)['valid'] is True
    active = Wristband.query.filter_by(is_active=True).order_by(Wristband.number).all()
    assert [row.number for row in active] == [f'{n:03}' for n in range(1,101)]
    assert all(row.bath_area == ('male' if int(row.number) <= 50 else 'female') for row in active)
    assert db.session.get(Wristband, ids['band_id']).number == '8001'
    assert not db.session.get(Wristband, ids['band_id']).is_active
    assert db.session.get(Member, ids['member_id']).balance == Decimal(25)
    assert db.session.get(CatalogItem, ids['water_id']).stock_quantity == Decimal(5)
    assert db.session.get(CatalogItem, ids['towel_id']).reference_code == 'bath.towel'
    assert db.session.get(CatalogItem, ids['towel_id']).stock_quantity == Decimal(8)
    assert CatalogItem.query.filter_by(reference_code='bath.supplies').one().stock_quantity == 0
    assert db.session.get(OrderItem, ids['line_id']).total_amount == Decimal(3)
    assert AuditLog.query.filter_by(action='fixture.original').one().current_hash == original_audit
    assert verify_audit_chain() == (True, None)
    CatalogItem.query.filter_by(reference_code='bath.mud').one().stock_quantity = 4
    db.session.commit()
    seed_defaults()
    preview = preview_upgrade(db.session); db.session.rollback()
    with db.engine.connect() as connection:
        second = apply_upgrade(connection, preview_digest(preview), 'unused-test-receipt')
    db.session.expire_all()
    assert second['applied'] is False
    assert Wristband.query.filter_by(is_active=True).count() == 100
    assert CatalogItem.query.filter_by(reference_code='bath.mud').one().stock_quantity == 4
    assert AuditLog.query.filter_by(action='operations.upgrade').count() == 1


def test_stale_preview_or_invalid_backup_cannot_start_maintenance(legacy_app, monkeypatch):
    from app.operations_upgrade import OperationsUpgradeError, apply_upgrade, preview_upgrade, preview_digest
    from app.operations_backup import BackupReceiptError
    _, ids = legacy_app
    digest = preview_digest(preview_upgrade(db.session))
    db.session.get(CatalogItem, ids['water_id']).stock_quantity = 4
    db.session.commit()
    with db.engine.connect() as connection, pytest.raises(OperationsUpgradeError):
        apply_upgrade(connection, digest, 'unused')
    assert not db.session.get(BusinessStateModel, 1).maintenance
    current_digest = preview_digest(preview_upgrade(db.session)); db.session.rollback()
    def reject(*_args): raise BackupReceiptError('Unverified backup')
    monkeypatch.setattr('app.operations_backup.validate_backup_receipt', reject)
    with db.engine.connect() as connection, pytest.raises(BackupReceiptError):
        apply_upgrade(connection, current_digest, 'unused')
    assert Wristband.query.filter_by(is_active=True).count() == 120


def test_failed_business_transaction_leaves_maintenance_and_no_half_catalog(legacy_app, monkeypatch):
    from app.operations_upgrade import apply_upgrade, preview_upgrade, preview_digest
    _, _ids = legacy_app
    digest = preview_digest(preview_upgrade(db.session)); db.session.rollback()
    monkeypatch.setattr('app.operations_backup.validate_backup_receipt', lambda *_args: {})
    def fail(session):
        session.query(CatalogItem).first().price = 999
        session.flush()
        raise RuntimeError('injected disk failure')
    monkeypatch.setattr('app.operations_upgrade.apply_formal_catalog', fail)
    with db.engine.connect() as connection, pytest.raises(RuntimeError, match='disk failure'):
        apply_upgrade(connection, digest, 'unused')
    db.session.expire_all()
    state = db.session.get(BusinessStateModel, 1)
    assert state.maintenance and state.maintenance_reset_id == 'operations-20261004'
    assert Wristband.query.filter_by(is_active=True).count() == 120
    assert CatalogItem.query.filter_by(reference_code='ticket.adult').count() == 0
    assert not CatalogItem.query.filter_by(price=999).count()


def test_maintenance_application_does_not_register_public_business_actions(tmp_path):
    class Config(TestConfig):
        MAINTENANCE_PROCESS = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'maintenance.sqlite').as_posix()}"
    application = create_app(Config)
    assert not any(rule.rule.startswith('/api/auth') or rule.rule.startswith('/api/visits')
        for rule in application.url_map.iter_rules())
    assert 'operations-upgrade' in application.cli.commands


def test_upgrade_cannot_run_inside_http_even_with_a_test_connection(legacy_app):
    from app.operations_upgrade import OperationsUpgradeError, apply_upgrade
    application, _ids = legacy_app
    with application.test_request_context('/api/not-a-maintenance-endpoint'):
        with db.engine.connect() as connection, pytest.raises(OperationsUpgradeError, match='HTTP'):
            apply_upgrade(connection, 'not-valid', 'unused')
