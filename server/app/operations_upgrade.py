"""Explicit owner-only operational cutover. Never invoked by startup or HTTP."""
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

import click
from flask import current_app, has_request_context
from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit_service import write_audit
from .business_barrier import BARRIER_KEY, exclusive_barrier
from .catalog_defaults import formal_catalog_specs
from .extensions import db
from .models import (BusinessStateModel, CatalogItem, ResetTaskModel, SystemSetting,
    Visit, Wristband, utcnow)

TASK_ID = 'operations-20261004'
KEY = 'operations_upgrade_20261004'
NUMBERS = tuple(f'{n:03}' for n in range(1,101))


class OperationsUpgradeError(ValueError):
    pass


def preview_digest(preview):
    return hashlib.sha256(json.dumps(preview, sort_keys=True, ensure_ascii=False,
        separators=(',',':')).encode('utf-8')).hexdigest()


def preview_upgrade(session):
    from .operations_backup import snapshot_identity
    identity = snapshot_identity(session.connection())
    state = session.get(BusinessStateModel, 1)
    catalogs = session.query(CatalogItem).order_by(CatalogItem.id).all()
    bands = session.query(Wristband).order_by(Wristband.number).all()
    marker = session.query(SystemSetting).filter_by(key=KEY).first()
    visits = session.query(Visit).filter(Visit.status.in_(['open','settling'])).all()
    lost = [band.id for band in bands if band.is_active and band.status != 'available']
    blockers = sorted(set(lost + [visit.wristband_id for visit in visits]))
    conflicts = []
    if blockers: conflicts.append('UNFINISHED_WRISTBANDS')
    if session.query(ResetTaskModel).filter(ResetTaskModel.status.in_(['queued','running'])).first():
        conflicts.append('RESET_PENDING')
    if state.maintenance: conflicts.append('MAINTENANCE_ALREADY_ACTIVE')
    if not marker:
        if any(band.number in NUMBERS for band in bands): conflicts.append('TARGET_NUMBER_EXISTS')
        if any(item.reference_code is not None for item in catalogs): conflicts.append('REFERENCE_CODE_EXISTS')
        if len([item for item in catalogs if item.kind=='product' and item.name in {'澡巾','一次性搓澡巾'}]) > 1:
            conflicts.append('AMBIGUOUS_TOWEL')
        other_names = {spec.name for spec in formal_catalog_specs() if spec.stock_tracked and spec.reference_code!='bath.towel'}
        if any(item.kind=='product' and item.name in other_names for item in catalogs):
            conflicts.append('AMBIGUOUS_FORMAL_PRODUCT')
    return dict(schema=1, task_id=TASK_ID, **identity, already_applied=bool(marker),
        can_apply=not conflicts, conflicts=conflicts, blocking_wristband_ids=blockers,
        retired_service_ids=[item.id for item in catalogs if item.is_active and item.kind in {'service','ticket','package'}],
        retained_products={item.id:dict(name=item.name, stock_quantity=str(item.stock_quantity), price=str(item.price))
            for item in catalogs if item.kind=='product'},
        old_wristband_numbers=[band.number for band in bands], new_wristband_numbers=list(NUMBERS),
        catalog_snapshot=[dict(id=item.id, version=item.version, kind=item.kind, name=item.name,
            reference_code=item.reference_code, price=str(item.price), stock=str(item.stock_quantity),
            is_active=item.is_active, sort_order=item.sort_order, package_definition=item.package_definition) for item in catalogs],
        wristband_snapshot=[dict(id=band.id, number=band.number, version=band.version, status=band.status,
            is_active=band.is_active, bath_area=band.bath_area) for band in bands])


def _require_owner(connection):
    if has_request_context():
        raise OperationsUpgradeError('Maintenance cannot run in an HTTP request')
    if connection.dialect.name == 'sqlite':
        if not current_app.config.get('TESTING'):
            raise OperationsUpgradeError('Operational cutover requires the production PostgreSQL maintenance login')
        return
    if connection.dialect.name != 'postgresql':
        raise OperationsUpgradeError('Unsupported maintenance database')
    # Actual login and actual table owners, not role membership / current_user.
    row = connection.exec_driver_sql("""SELECT
      (SELECT oid FROM pg_catalog.pg_roles WHERE rolname=session_user),
      (SELECT CASE WHEN r.rolname='pg_database_owner' THEN d.datdba ELSE n.nspowner END
       FROM pg_catalog.pg_namespace n JOIN pg_catalog.pg_roles r ON r.oid=n.nspowner
       JOIN pg_catalog.pg_database d ON d.datname=current_database() WHERE n.nspname='public'),
      ARRAY(SELECT c.relowner FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p'))""").one()
    if row[0] != row[1] or not row[2] or any(owner != row[0] for owner in row[2]):
        raise OperationsUpgradeError('Maintenance requires the actual schema and business table owner login')


@contextmanager
def maintenance_connection():
    with db.engine.connect() as connection:
        _require_owner(connection)
        connection.rollback()
        yield connection


def verify_preview_and_backup(connection, preview_sha, backup_receipt):
    from .operations_backup import validate_backup_receipt
    with Session(bind=connection) as session:
        preview = preview_upgrade(session)
        if not preview['can_apply'] or preview_digest(preview) != preview_sha:
            raise OperationsUpgradeError('Preview changed or unfinished business blocks this cutover; inspect a new preview')
        if not preview['already_applied']:
            validate_backup_receipt(connection, Path(backup_receipt), preview['alembic_revision'])
    return preview


def mark_maintenance(connection, task_id):
    connection.execute(BusinessStateModel.__table__.update().where(BusinessStateModel.id==1)
        .values(maintenance=True, maintenance_reset_id=task_id))


def apply_formal_catalog(session):
    existing = session.query(CatalogItem).order_by(CatalogItem.sort_order, CatalogItem.id).all()
    if any(item.reference_code for item in existing):
        raise OperationsUpgradeError('Formal reference codes already exist; refuse to overwrite')
    towels = [item for item in existing if item.kind=='product' and item.name in {'澡巾','一次性搓澡巾'}]
    if len(towels)>1:
        raise OperationsUpgradeError('Multiple towel items require manual reconciliation')
    for item in existing:
        if item.kind in {'service','ticket','package'} and item.is_active:
            item.is_active = False
            item.version += 1
    result = {}
    for spec in formal_catalog_specs():
        item = towels[0] if spec.reference_code=='bath.towel' and towels else CatalogItem(stock_quantity=0)
        if item not in existing: session.add(item)
        else: item.version += 1
        for name in ('reference_code','kind','category','name','price','mobile_scope','stock_tracked','sort_order'):
            setattr(item, name, getattr(spec, name))
        item.is_active = True
        result[spec.reference_code] = item
    session.flush()
    for spec in formal_catalog_specs():
        if spec.kind=='package':
            result[spec.reference_code].package_definition = dict(schema=1, display_contents=list(spec.display_contents),
                slots=[dict(catalog_item_ids=[result[code].id for code in choices], quantity='1.000') for choices in spec.package_slots])
    # Keep product UUIDs, quantity, prices and their relative order intact.
    for index,item in enumerate(item for item in existing if item.kind=='product' and item not in towels):
        item.sort_order = 1000 + index*10
        item.version += 1
    return result


def retire_legacy_wristbands_and_create_hundred(session):
    bands = session.query(Wristband).all()
    if any(band.number in NUMBERS for band in bands):
        raise OperationsUpgradeError('Target wristband numbers already exist')
    for band in bands:
        if band.is_active:
            if band.status != 'available': raise OperationsUpgradeError('Unfinished wristband blocks replacement')
            band.is_active = False
            band.version += 1
    created = [Wristband(number=number, bath_area='male' if int(number)<=50 else 'female') for number in NUMBERS]
    session.add_all(created); session.flush()
    return dict(retired_ids=[band.id for band in bands], new_ids=[band.id for band in created])


def record_upgrade_audit(session, preview):
    write_audit('operations.upgrade', 'system_setting', KEY,
        dict(preview_sha256=preview_digest(preview), before=preview,
            after=dict(active_wristbands=100, formal_items=42, previous_records_preserved=True)), session=session)


def clear_maintenance_in_same_success_transaction(session):
    state = session.get(BusinessStateModel,1)
    if state.maintenance_reset_id != TASK_ID:
        raise OperationsUpgradeError('Unexpected maintenance ownership; refuse to clear')
    state.maintenance = False
    state.maintenance_reset_id = None


def apply_upgrade(connection, preview_sha, backup_receipt):
    _require_owner(connection)
    with exclusive_barrier(connection, TASK_ID):
        preview = verify_preview_and_backup(connection, preview_sha, backup_receipt)
        connection.rollback()
        if preview['already_applied']:
            with Session(bind=connection) as session:
                result = verify_upgrade(session)
                if not result['valid']: raise OperationsUpgradeError('Previously applied upgrade does not verify')
            return dict(applied=False, **result)
        with connection.begin():
            mark_maintenance(connection, TASK_ID)
        with Session(bind=connection) as session:
            apply_formal_catalog(session)
            retire_legacy_wristbands_and_create_hundred(session)
            from .catalog_layout import touch_catalog_layout
            touch_catalog_layout(session)
            record_upgrade_audit(session, preview)
            session.add(SystemSetting(key=KEY, value=dict(schema=1, preview_sha256=preview_sha,
                applied_at=utcnow().isoformat()), description='正式营业目录和手牌切换证据'))
            clear_maintenance_in_same_success_transaction(session)
            session.commit()
        return dict(applied=True, active_wristbands=100, formal_items=42)


def verify_upgrade(session):
    bands = session.query(Wristband).filter_by(is_active=True).order_by(Wristband.number).all()
    formal = session.query(CatalogItem).filter(CatalogItem.reference_code.is_not(None)).all()
    codes = {spec.reference_code for spec in formal_catalog_specs()}
    valid = (len(bands)==100 and tuple(band.number for band in bands)==NUMBERS
        and all(band.bath_area==('male' if int(band.number)<=50 else 'female') for band in bands)
        and len(formal)==42 and {item.reference_code for item in formal}==codes)
    return dict(valid=valid, active_wristbands=len(bands), formal_items=len(formal),
        maintenance=bool(session.get(BusinessStateModel,1).maintenance))


def register_operations_cli(app):
    @app.cli.group('operations-upgrade')
    def operations_cli():
        """Private owner maintenance, never an HTTP action."""

    @operations_cli.command('preview')
    @click.option('--output', required=True, type=click.Path(path_type=Path))
    def preview_command(output):
        from .operations_backup import private_path
        with maintenance_connection() as connection, Session(bind=connection) as session:
            result = preview_upgrade(session)
        # The destination directory must already be private; no public outputs.
        private_path(output.parent, directory=True)
        with output.open('x', encoding='utf-8') as stream:
            __import__('os').chmod(output,0o600)
            stream.write(json.dumps(result,ensure_ascii=False,indent=2))
        click.echo(json.dumps(dict(preview_sha256=preview_digest(result),can_apply=result['can_apply'],
            conflicts=result['conflicts']),ensure_ascii=False))

    @operations_cli.command('apply')
    @click.option('--preview-sha256', required=True)
    @click.option('--backup-receipt', required=True, type=click.Path(exists=True,path_type=Path))
    @click.option('--confirm', required=True)
    def apply_command(preview_sha256, backup_receipt, confirm):
        if confirm != TASK_ID: raise click.ClickException('Incorrect operational confirmation')
        try:
            with maintenance_connection() as connection:
                result = apply_upgrade(connection,preview_sha256,backup_receipt)
        except ValueError as error:
            raise click.ClickException(str(error)) from None
        click.echo(json.dumps(result,ensure_ascii=False))

    @operations_cli.command('verify')
    def verify_command():
        with maintenance_connection() as connection, Session(bind=connection) as session:
            result = verify_upgrade(session)
        click.echo(json.dumps(result,ensure_ascii=False))
        if not result['valid']: raise click.ClickException('Operational upgrade did not verify')
