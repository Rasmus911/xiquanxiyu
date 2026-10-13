"""Executable PG17 clone proof. No production endpoint or URL is accepted."""
import os
import hashlib
import json
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from desktop_051_guard import NEW, prove_runtime_roles, require, require_isolated


def validate_endpoints(urls):
    for url in urls:
        require_isolated(url)
    require(len({(u.host, u.port or 5432, u.database) for u in urls}) == 1, 'Different isolated endpoints')


def parallel(first, second):
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(function) for function in (first, second)]
        return [future.result(timeout=45) for future in futures]


def denied(engine, sql, values, codes, *, read_write=False):
    if read_write:
        require_isolated(engine.url)
    with engine.connect() as connection:
        if read_write:
            connection.exec_driver_sql('SET TRANSACTION READ WRITE')
        try:
            connection.execute(text(sql), values)
        except DBAPIError as error:
            require(getattr(error.orig, 'sqlstate', None) in codes, 'Wrong PostgreSQL denial')
            connection.rollback()
            return error.orig.sqlstate
        else:
            connection.rollback()
            raise RuntimeError('Forbidden database operation succeeded')


def prove_backup_write_denials(engine):
    require_isolated(engine.url)
    with engine.connect() as connection:
        require(connection.exec_driver_sql('SELECT session_user').scalar_one() == 'xiquan_backup', 'Backup identity differs')
        for setting in ('default_transaction_read_only', 'transaction_read_only'):
            require(connection.exec_driver_sql('SHOW ' + setting).scalar_one() == 'on', 'Backup read-only policy differs')
    sql = 'UPDATE member_card_bindings SET version=version+1'
    return dict(default_readonly=denied(engine, sql, {}, {'25006'}),
                readwrite_acl=denied(engine, sql, {}, {'42501'}, read_write=True))


def exercise(app, connection, job):
    from app import create_app
    from app.extensions import db
    from app.config import Config
    from app.business_barrier import exclusive_barrier
    from app.auth_service import hash_password
    from app.models import Employee, Terminal, Wristband, Visit, OrderItem, Member, MemberPass
    from app.member_cards import bind_physical_card
    from app.access_policy import active_policy, policy_claims
    from flask_jwt_extended import create_access_token

    urls = {key: make_url(os.environ[name]) for key, name in (
        ('runtime', 'RUNTIME_DATABASE_URL'), ('reset', 'RESET_DATABASE_URL'), ('backup', 'RESET_BACKUP_DATABASE_URL'))}
    validate_endpoints([db.engine.url, *urls.values()])
    require(int(connection.exec_driver_sql('SHOW server_version_num').scalar_one()) // 10000 == 17, 'Actual PG17 required')
    roles = prove_runtime_roles(connection)
    version = connection.exec_driver_sql('SHOW server_version').scalar_one()
    # Only this clone's owned maintenance may be released for fixture requests.
    with exclusive_barrier(connection, job):
        require(connection.execute(text('SELECT maintenance_reset_id FROM business_state WHERE id=1')).scalar_one() == job,
                'Clone maintenance identity differs')
        connection.exec_driver_sql('UPDATE business_state SET maintenance=false,maintenance_reset_id=NULL WHERE id=1')
        connection.commit()
    runtime = create_engine(urls['runtime'], hide_parameters=True)
    backup = create_engine(urls['backup'], hide_parameters=True)
    actual_roles = {'owner': connection.exec_driver_sql('SELECT session_user').scalar_one()}
    for kind, expected in (('runtime', 'xiquan_app'), ('reset', 'xiquan_reset'), ('backup', 'xiquan_backup')):
        engine = create_engine(urls[kind], hide_parameters=True)
        try:
            with engine.connect() as check:
                actual_roles[kind] = check.exec_driver_sql('SELECT session_user').scalar_one()
                require(actual_roles[kind] == expected, 'Actual database login differs')
                for table in NEW: check.exec_driver_sql('SELECT count(*) FROM ' + table).scalar_one()
        finally: engine.dispose()
    password = secrets.token_urlsafe(32)
    suffix = uuid.uuid4().hex
    with app.app_context():
        staff = [Employee(username='proof-' + suffix[:20] + str(i), display_name='Isolated proof',
                         password_hash=hash_password(password), role='cashier', allowed_channels=['desktop']) for i in range(2)]
        terminal = Terminal(code='proof-' + suffix, name='Isolated proof')
        db.session.add_all([*staff, terminal]); db.session.commit()
        employee_ids, terminal_id = [row.id for row in staff], terminal.id

    class RuntimeConfig(Config):
        # Tokens issued for clone fixtures must never authenticate to production.
        SECRET_KEY = secrets.token_urlsafe(48)
        JWT_SECRET_KEY = secrets.token_urlsafe(48)
        SQLALCHEMY_DATABASE_URI = urls['runtime'].render_as_string(hide_password=False)
        SQLALCHEMY_ENGINE_OPTIONS = {'pool_pre_ping': True, 'connect_args': {'options': '-c statement_timeout=25000 -c lock_timeout=15000'}}
        MAINTENANCE_PROCESS = False
        RESET_WORKER_ENABLED = False
        AUTO_CREATE_DB = False
        SMS_ENABLED = False
        SOCKETIO_ASYNC_MODE = 'threading'

    runtime_app = create_app(RuntimeConfig)
    headers = []
    with runtime_app.app_context():
        for employee_id in employee_ids:
            employee = db.session.get(Employee, employee_id)
            claims = dict(policy_claims(employee, 'desktop'), terminal_id=terminal_id,
                          session_version=employee.session_version, session_id=str(uuid.uuid4()))
            token = create_access_token(employee_id, additional_claims=claims, expires_delta=timedelta(minutes=10))
            headers.append({'Authorization': 'Bearer ' + token, 'X-Business-Period': claims['business_period_id']})
        db.session.remove()

    def request(method, route, body=None, principal=0):
        with runtime_app.test_client() as client:
            response = client.open(route, method=method, json=body, headers=headers[principal])
            value = response.get_json()
            require(isinstance(value, dict), 'Endpoint did not return JSON')
            return response.status_code, value

    def open_card(kind):
        payload = dict(card_uid='00' + str(uuid.uuid4().int), phone=None, holder_surname=None,
            surname_confirmed=False, membership_type=kind, amount='15', count=1,
            pass_name='Isolated proof', payment_method='cash', idempotency_key=uuid.uuid4().hex)
        status, result = request('POST', '/api/members/physical-open', payload)
        require(status == 201 and result['data']['member']['phone'] == '', 'Nullable phone opening failed')
        return result['data']

    def visit():
        with app.app_context():
            band = Wristband(number='proof-' + uuid.uuid4().hex[:23], bath_area='male', status='in_use')
            db.session.add(band); db.session.flush()
            row = Visit(wristband_id=band.id, opened_by_id=employee_ids[0])
            db.session.add(row); db.session.flush()
            db.session.add(OrderItem(visit_id=row.id, kind='ticket', name_snapshot='Isolated ticket',
                unit_price=15, quantity=1, covered_quantity=0, total_amount=15, created_by_id=employee_ids[0]))
            db.session.commit()
            return row.id

    def checkout(card, visit_id, kind):
        body = dict(visit_ids=[visit_id], checkout_scope='selected', member_id=card['member']['id'],
            member_verification=dict(method='card', card_binding_id=card['card_binding']['id'], surname_confirmed=False),
            payments=[dict(method='balance', amount='15')] if kind == 'stored' else [], idempotency_key=uuid.uuid4().hex)
        if kind == 'pass': body['pass_use'] = dict(member_pass_id=card['member_pass']['id'], visit_ids=[visit_id])
        return body

    results, cards = {}, {}
    try:
        for kind, expected_code in (('stored', 'INSUFFICIENT_BALANCE'), ('pass', 'INSUFFICIENT_PASS')):
            card = cards[kind] = open_card(kind)
            bodies = [checkout(card, visit(), kind) for _ in range(2)]
            gate = threading.Barrier(2)
            pids = []
            def settle(index):
                with runtime_app.app_context():
                    pids.append(db.session.execute(text('SELECT pg_backend_pid()')).scalar_one())
                    gate.wait(timeout=10)
                    return request('POST', '/api/checkout', bodies[index], index)
            replies = parallel(lambda: settle(0), lambda: settle(1))
            require(len(set(pids)) == 2, 'Concurrency requires two actual PostgreSQL connections')
            require(sorted(status for status, _ in replies) == [201, 409], 'Double-spend was not rejected')
            failure = next(value for status, value in replies if status == 409)
            require(failure['error']['code'] == expected_code, 'Wrong double-spend rejection')
            with runtime_app.app_context():
                if kind == 'stored': remaining = db.session.get(Member, card['member']['id']).balance
                else: remaining = db.session.get(MemberPass, card['member_pass']['id']).remaining_count
                require(remaining == 0, 'Resource went negative or debit missing')
                require(db.session.get(Member, card['member']['id']).phone is None, 'Missing phone was not stored as SQL NULL')
            results[kind + '_concurrency'] = dict(backend_pids=pids, successes=1, denials=1, remaining='0')

        # A replacement holds the application's financial lock; the old-card
        # checkout must be blocked until commit, then fail binding revalidation.
        card = open_card('stored'); body = checkout(card, visit(), 'stored')
        replacement_ready, contender_ready = threading.Event(), threading.Event()
        contender_pid = []
        def replace():
            with runtime_app.app_context():
                member = db.session.get(Member, card['member']['id'])
                employee = db.session.get(Employee, employee_ids[0])
                terminal = db.session.get(Terminal, terminal_id)
                bind_physical_card(member, employee, terminal, dict(card_uid='00' + str(uuid.uuid4().int),
                    password=password, idempotency_key=uuid.uuid4().hex))
                replacement_ready.set()
                require(contender_ready.wait(10), 'Checkout contender did not start')
                deadline, blocked = time.monotonic() + 10, False
                while time.monotonic() < deadline:
                    with runtime.connect() as observer:
                        blocked = observer.execute(text("SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=:pid"),
                                                   dict(pid=contender_pid[0])).scalar_one()
                    if blocked: break
                    time.sleep(.05)
                require(blocked, 'Old-card checkout did not wait for replacement lock')
                db.session.commit()
                return 'replacement-committed'
        def stale_checkout():
            require(replacement_ready.wait(10), 'Replacement did not acquire lock')
            with runtime_app.app_context():
                contender_pid.append(db.session.execute(text('SELECT pg_backend_pid()')).scalar_one())
                contender_ready.set()
                return request('POST', '/api/checkout', body, 1)
        replaced, reply = parallel(replace, stale_checkout)
        require(reply[0] == 409 and reply[1]['error']['code'] == 'INVALID_CARD_BINDING', 'Old card settled after replacement')
        results['replacement_concurrency'] = dict(waited=True, old_card_rejected=True)

        binding_id = cards['stored']['card_binding']['id']
        for table in sorted(NEW):
            for verb in ('DELETE FROM', 'TRUNCATE'):
                denied(runtime, verb + ' ' + table, {}, {'42501'})
        denied(runtime, 'UPDATE member_card_bindings SET card_uid=:uid WHERE id=:id',
               dict(uid='999', id=binding_id), {'42501'})
        denied(runtime, 'UPDATE settlement_pass_redemptions SET amount=0', {}, {'42501'})
        denied(db.engine, 'UPDATE settlement_pass_redemptions SET amount=0', {}, {'P0001'})
        # Database uniqueness applies even to raw SQL that bypasses API checks.
        clone_sql = '''INSERT INTO member_card_bindings
            (id,period_id,member_id,card_uid,is_active,created_by,terminal_id,created_at,updated_at,version)
            SELECT :new_id,period_id,member_id,card_uid,:active,created_by,terminal_id,now(),now(),1
            FROM member_card_bindings WHERE id=:id'''
        denied(runtime, clone_sql, dict(new_id=str(uuid.uuid4()), active=False, id=binding_id), {'23505'})
        denied(runtime, clone_sql.replace('member_id,card_uid,:active', 'member_id,:uid,:active'),
               dict(new_id=str(uuid.uuid4()), active=True, id=binding_id, uid='00' + str(uuid.uuid4().int)), {'23505'})
        denied(runtime, clone_sql.replace('SELECT :new_id,period_id,', 'SELECT :new_id,:period,'),
               dict(new_id=str(uuid.uuid4()), period=str(uuid.uuid4()), active=False, id=binding_id), {'P0001'})
        with runtime.begin() as check:
            require(check.execute(text('UPDATE member_card_bindings SET version=version+1 WHERE id=:id'), dict(id=binding_id)).rowcount == 1,
                    'Runtime state-only update failed')
        with backup.connect() as check:
            require(check.exec_driver_sql('SELECT session_user').scalar_one() == 'xiquan_backup', 'Backup identity differs')
            for table in NEW: require(check.exec_driver_sql('SELECT count(*) FROM ' + table).scalar_one() > 0, 'Backup cannot read fixtures')
        results['backup_write_denials'] = prove_backup_write_denials(backup)
        with exclusive_barrier(connection, job):
            connection.execute(text('UPDATE business_state SET maintenance=true,maintenance_reset_id=:job WHERE id=1'), dict(job=job))
            connection.commit()
            denied(runtime, 'UPDATE member_card_bindings SET version=version+1 WHERE id=:id', dict(id=binding_id), {'P0001'})
            connection.exec_driver_sql('UPDATE business_state SET maintenance=false,maintenance_reset_id=NULL WHERE id=1')
            connection.commit()
        results.update(null_phone=True, card_unique=True, active_binding_unique=True, append_only=True,
                       period_guard=True, maintenance_barrier=True, backup_readable=True, runtime_roles=roles)
        legacy_visit = visit()
        status, value = request('POST', '/api/checkout', dict(visit_ids=[legacy_visit],
            payments=[dict(method='cash', amount='15')], idempotency_key=uuid.uuid4().hex))
        require(status == 201 and value['data']['total_amount'] == '15.00' and
                value['data']['paid_amount'] == '15.00', 'Legacy checkout payload is incompatible')
        reads = {}
        for label, channel in (('desktop-old', 'desktop'), ('desktop-new', 'desktop'), ('web', 'web'), ('mobile-1.2.9', 'mobile')):
            with runtime_app.app_context():
                owner = db.session.get(Employee, active_policy().owner_id)
                claims = dict(policy_claims(owner, channel), terminal_id=terminal_id, session_version=owner.session_version)
                token = create_access_token(owner.id, additional_claims=claims, expires_delta=timedelta(minutes=10))
                read_headers = {'Authorization': 'Bearer ' + token, 'X-Business-Period': claims['business_period_id']}
                db.session.remove()
            with runtime_app.test_client() as client:
                response = client.get('/api/wristbands', headers=read_headers)
                require(response.status_code == 200 and response.get_json()['success'], 'Legacy read endpoint incompatible')
                reads[label] = hashlib.sha256(json.dumps(response.get_json()['data'], sort_keys=True).encode()).hexdigest()
        require(len(set(reads.values())) == 1, 'Authenticated channels did not read the same data')
        results['compatibility'] = dict(scope='isolated authenticated endpoints; not actual devices',
                                       shared_wristband_hashes=reads, old_checkout_payload=True)
        return dict(pg17=True, isolated=True, database_version=version, database_roles=actual_roles,
                    fixture_scope='isolated restore only', **results)
    finally:
        runtime.dispose(); backup.dispose()
