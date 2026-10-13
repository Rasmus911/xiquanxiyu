"""Exact 0.5.0 identity/ephemeral-receipt migration; no financial conversion."""
import argparse
import importlib
import json
import uuid
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from app import create_app
from app.extensions import db
from app.business_barrier import exclusive_barrier
from app.operations_upgrade import maintenance_connection
from app.operations_backup import _verify_snapshot_audit
from app.employee_identity import HISTORICAL_EMPLOYEE_REFERENCES
from stock_guard import roles, state, revision, GuardError, require

OLD = '20261008_registration_token'
HEAD = '20261011_service_receipts'
NEW = {'employee_identities', 'service_print_jobs', 'service_print_attempts', 'settlement_print_attempts'}
JOBS = ('print_jobs', 'service_print_jobs')
ATTEMPTS = ('service_print_attempts', 'settlement_print_attempts')


def require_isolated(url):
    require(bool(url.host) and url.host.startswith('xiquan-operations-restore-') and
            url.database == 'operations_restore', 'Writes require an isolated restore endpoint')


def row_hash(connection, query):
    count, digest = connection.exec_driver_sql('''SELECT count(*), encode(sha256(convert_to(
        COALESCE(string_agg(to_jsonb(t)::text,E'\\n' ORDER BY to_jsonb(t)::text COLLATE "C"),''),
        'UTF8')),'hex') FROM (''' + query + ') t').one()
    return dict(rows=count, sha256=digest)


def receipt_privileges(connection):
    for table in JOBS + ATTEMPTS:
        allowed = ('status', 'attempts', 'last_error', 'printed_at', 'updated_at') if table in JOBS else (
            'success', 'error', 'finished_at', 'updated_at')
        for privilege in ('DELETE', 'TRUNCATE', 'UPDATE'):
            if connection.execute(text('SELECT has_table_privilege(:role,:table,:privilege)'),
                                  dict(role='xiquan_app', table=table, privilege=privilege)).scalar_one(): return False
        for column in inspect(connection).get_columns(table):
            actual = connection.execute(text('SELECT has_column_privilege(:role,:table,:column,\'UPDATE\')'),
                dict(role='xiquan_app', table=table, column=column['name'])).scalar_one()
            if actual != (column['name'] in allowed): return False
        for privilege in ('SELECT', 'INSERT'):
            if not connection.execute(text('SELECT has_table_privilege(:role,:table,:privilege)'),
                dict(role='xiquan_app', table=table, privilege=privilege)).scalar_one(): return False
    for role in ('xiquan_app', 'xiquan_reset', 'xiquan_backup'):
        for privilege in ('UPDATE', 'DELETE', 'TRUNCATE'):
            if connection.execute(text('SELECT has_table_privilege(:role,\'employee_identities\',:privilege)'),
                dict(role=role, privilege=privilege)).scalar_one(): return False
    return True


def snapshot(connection):
    require(connection.exec_driver_sql('SHOW server_version_num').scalar_one().startswith('17'), 'PG17 required')
    connection.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
    version = revision(connection)
    require(version in (OLD, HEAD), 'Unexpected schema revision')
    tables, columns, foreign_keys = {}, {}, {}
    inspector = inspect(connection)
    for table in sorted(inspector.get_table_names()):
        require(table.replace('_', '').isalnum(), 'Unexpected table identifier')
        columns[table] = {c['name']: dict(type=str(c['type']), nullable=c['nullable'], default=c['default'])
                          for c in inspector.get_columns(table)}
        query = 'SELECT to_jsonb(t)-\'version_num\' AS row FROM alembic_version t' if table == 'alembic_version' else f'SELECT * FROM public."{table}"'
        tables[table] = row_hash(connection, query)
        foreign_keys[table] = sorted([dict(columns=fk['constrained_columns'], table=fk['referred_table'],
            referred=fk['referred_columns']) for fk in inspector.get_foreign_keys(table)], key=lambda x:json.dumps(x,sort_keys=True))
    role_hash = connection.exec_driver_sql("""SELECT encode(sha256(convert_to(string_agg(
        row_to_json(r)::text,E'\n' ORDER BY rolname),'UTF8')),'hex') FROM pg_authid r
        WHERE rolname IN ('xiquan_app','xiquan_reset','xiquan_backup')""").scalar_one()
    owners = dict(connection.exec_driver_sql("""SELECT c.relname,pg_get_userbyid(c.relowner)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p')""").all())
    grants = {name:list(acl or []) for name,acl in connection.exec_driver_sql("""SELECT c.relname,
        ARRAY(SELECT a::text FROM unnest(COALESCE(c.relacl,acldefault('r',c.relowner))) a ORDER BY a::text)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p')""")}
    # Match exactly the migration's approved removal: only pre-existing soft-deleted,
    # non-admin accounts not referenced by ANY retained access/reset policy.
    retained = """SELECT e.* FROM employees e WHERE e.deleted_at IS NULL OR e.role='admin' OR
        EXISTS(SELECT 1 FROM access_policies p WHERE p.owner_id=e.id OR
          COALESCE(p.mobile_employee_ids::jsonb,'[]'::jsonb) ? e.id OR
          COALESCE(p.administrator_employee_ids::jsonb,'[]'::jsonb) ? e.id) OR
        EXISTS(SELECT 1 FROM reset_tasks r WHERE r.owner_id=e.id)"""
    identity = row_hash(connection, 'SELECT id,username,display_name,role,created_at FROM employees')
    require(_verify_snapshot_audit(connection), 'Audit evidence invalid')
    return dict(tables=tables,columns=columns,foreign_keys=foreign_keys,roles=role_hash,owners=owners,grants=grants,
        schema=version,audit_valid=True,retained_employees=row_hash(connection,retained),identity_expected=identity,
        receipt_privileges_valid=receipt_privileges(connection) if version==HEAD else False)


def compare_retained_rows(before_tables, after_tables, names):
    for name in names:
        require(name in before_tables and name in after_tables, 'Retained table missing: '+name)
        require(before_tables[name]==after_tables[name], 'Retained data changed: '+name)


def compare(before, after):
    require(before['schema']==OLD and after['schema']==HEAD, 'Unexpected schema changed')
    require(not(set(before['tables']) & NEW) and set(after['tables'])==set(before['tables'])|NEW,
            'Unexpected table addition/removal')
    require(before['roles']==after['roles'], 'Database roles changed')
    require(before['audit_valid'] and after['audit_valid'], 'Audit evidence changed')
    compare_retained_rows(before['tables'],after['tables'],tuple(set(before['tables'])-{'employees'}))
    require(after['tables']['employees']==before['retained_employees'], 'Unreviewed employee change')
    require(after['tables']['employee_identities']==before['identity_expected'], 'Historical identity changed')
    for name in before['tables']:
        require(before['columns'][name]==after['columns'][name], 'Retained columns changed: '+name)
        require(before['owners'][name]==after['owners'][name], 'Retained ownership changed: '+name)
        if name!='print_jobs': require(before['grants'][name]==after['grants'][name], 'Retained grants changed: '+name)
        else:
            other=lambda grants:[acl for acl in grants if not acl.startswith('xiquan_app=')]
            require(other(before['grants'][name])==other(after['grants'][name]),'Other print grants changed')
        expected=[]
        for original in before['foreign_keys'].get(name,[]):
            fk=dict(original)
            if fk['table']=='employees' and fk['columns'] in [[c] for c in HISTORICAL_EMPLOYEE_REFERENCES.get(name,())]:
                fk['table']='employee_identities'
            expected.append(fk)
        require(sorted(expected,key=lambda x:json.dumps(x,sort_keys=True))==after['foreign_keys'].get(name,[]),
                'Unexpected historical foreign key changed: '+name)
    require(all(after['owners'][name]==before['owners']['employees'] for name in NEW), 'New table owner changed')
    require(all(after['tables'][name]['rows']==0 for name in NEW-{'employee_identities'}), 'Migration created receipt fixtures')
    require(after['receipt_privileges_valid'], 'Receipt grants changed or excessive')


def migrate(connection):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with Operations.context(MigrationContext.configure(connection)):
        for name in ('20261011_employee_identity',HEAD):
            importlib.import_module('migrations.versions.'+name).upgrade()
    connection.execute(text('UPDATE alembic_version SET version_num=:head'),dict(head=HEAD))


def exercise(app, connection, job):
    require_isolated(db.engine.url)
    urls=roles()
    for url in urls.values(): require_isolated(url)
    # Existing registration competition, one-use, expiry-after-lock and evidence
    # tests run in this clone. The implementation does not accept production URLs.
    from desktop_049_guard import exercise as registration_proof
    proof=registration_proof(app,connection,job)
    runtime=create_engine(urls['runtime'],hide_parameters=True)
    from app.models import Terminal,Wristband,Visit
    from app.receipt_models import ServicePrintJob
    from app.receipt_retention import cleanup_expired_receipts_with_owner,business_day_bounds
    from datetime import datetime,timedelta,timezone
    with app.app_context():
        employee=db.session.execute(text('SELECT id FROM employees ORDER BY id LIMIT 1')).scalar_one()
        terminal=Terminal(code='receipt-proof-'+uuid.uuid4().hex,name='Isolated print proof')
        band=Wristband(number='proof-'+uuid.uuid4().hex[:24],bath_area='male')
        db.session.add_all([terminal,band]);db.session.flush()
        visit=Visit(wristband_id=band.id,opened_by_id=employee,status='closed')
        db.session.add(visit);db.session.flush()
        cutoff=business_day_bounds(datetime.now(timezone.utc))[0]
        ticket=ServicePrintJob(visit_id=visit.id,terminal_id=terminal.id,employee_id=employee,
            submission_key=uuid.uuid4().hex,bath_area='male',snapshot={'proof':True},created_at=cutoff-timedelta(seconds=1))
        db.session.add(ticket);db.session.commit()
        ticket_id=ticket.id
    for table,sql in [('employee_identities',"UPDATE employee_identities SET username='tampered' WHERE id=:id"),
                      ('service_print_jobs',"UPDATE service_print_jobs SET snapshot='{}'::json WHERE id=:id")]:
        for engine in (runtime,db.engine):
            with engine.connect() as check:
                try: check.execute(text(sql),dict(id=employee if table=='employee_identities' else ticket_id))
                except Exception as error:
                    require(getattr(getattr(error,'orig',None),'sqlstate',None) in ('42501','P0001'), 'Wrong immutability denial')
                    check.rollback()
                else: check.rollback();raise GuardError('Immutable data was writable')
    with runtime.connect() as check:
        for table in JOBS+ATTEMPTS+('employee_identities',):
            for operation in ('DELETE FROM','TRUNCATE'):
                try: check.exec_driver_sql(operation+' '+table)
                except Exception as error:
                    require(getattr(getattr(error,'orig',None),'sqlstate',None)=='42501','Runtime destructive grant allowed')
                    check.rollback()
                else: check.rollback();raise GuardError('Runtime destructive write allowed')
    with db.engine.connect() as check:
        before=snapshot(check);before_state=state(check);check.rollback()
        counts=cleanup_expired_receipts_with_owner(check)
        require(counts['order_jobs']>=1,'Expired clone receipt was not removed')
        after=snapshot(check)
        compare_retained_rows(before['tables'],after['tables'],tuple(set(before['tables'])-set(JOBS+ATTEMPTS)-{'business_state'}))
        after_state=state(check)
        removed=sum(before['tables'][name]['rows']-after['tables'][name]['rows'] for name in JOBS+ATTEMPTS)
        require(after_state['business_revision']==before_state['business_revision']+removed,'Unexpected cleanup revision')
        require({k:v for k,v in before_state.items() if k!='business_revision'}==
                {k:v for k,v in after_state.items() if k!='business_revision'},'Cleanup changed business state')
        require(not check.execute(text('SELECT id FROM service_print_jobs WHERE id=:id'),dict(id=ticket_id)).first(), 'Expired ticket retained')
        check.rollback()
    runtime.dispose()
    return dict(proof,identity_immutable=True,receipt_immutable=True,receipt_cleanup=True,retained_rows=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['inspect','claim','migrate','release','proof'])
    parser.add_argument('--job',required=True);parser.add_argument('--baseline')
    args=parser.parse_args();require(str(uuid.UUID(args.job))==args.job,'Invalid maintenance identity')
    app=create_app()
    with app.app_context(),maintenance_connection() as connection:
        if not db.engine.url.host.startswith('xiquan-operations-restore-'): roles()
        if args.mode=='proof': result=exercise(app,connection,args.job)
        elif args.mode=='inspect': result=snapshot(connection)
        else:
            with exclusive_barrier(connection,args.job):
                current=state(connection)
                require(not connection.exec_driver_sql("SELECT count(*) FROM reset_tasks WHERE status IN ('queued','running')").scalar_one(),'Pending reset')
                if args.mode=='claim':
                    require(revision(connection)==OLD and not current['maintenance'] and not current['maintenance_reset_id'],'Wrong predecessor/maintenance')
                    connection.execute(text('UPDATE business_state SET maintenance=true,maintenance_reset_id=:job WHERE id=1'),dict(job=args.job))
                    connection.commit();result=snapshot(connection)
                else:
                    require(current['maintenance'] and current['maintenance_reset_id']==args.job,'Maintenance belongs to another job')
                    before=snapshot(connection)
                    require(args.baseline and before==json.loads(Path(args.baseline).read_text()),'Checkpoint data changed')
                    if args.mode=='migrate':
                        require(revision(connection)==OLD,'Exact predecessor required')
                        migrate(connection);result=snapshot(connection);compare(before,result);connection.commit()
                    else:
                        require(revision(connection)==HEAD,'Expected new receipt schema')
                        connection.exec_driver_sql('UPDATE business_state SET maintenance=false,maintenance_reset_id=NULL WHERE id=1')
                        connection.commit();result=dict(released=True,schema=HEAD)
        print(json.dumps(result))


if __name__=='__main__':
    try: main()
    except Exception as error:
        message=str(error) if isinstance(error,GuardError) else type(error).__name__+': inspect private evidence'
        print('DESKTOP_GUARD_STOPPED: '+message,file=__import__('sys').stderr)
        raise SystemExit(1)
