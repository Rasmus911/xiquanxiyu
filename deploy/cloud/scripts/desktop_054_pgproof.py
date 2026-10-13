"""Real PG17 proof. Fixture writes are accepted only in an isolated restore."""
import hashlib
import json
import os
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from desktop_054_guard import NEW, prove_runtime_roles, require, require_isolated


def parallel(*functions):
    with ThreadPoolExecutor(max_workers=len(functions)) as pool:
        return [future.result(timeout=45) for future in [pool.submit(f) for f in functions]]


def denied(engine, sql, codes, *, read_write=False):
    require_isolated(engine.url)
    with engine.connect() as connection:
        if read_write: connection.exec_driver_sql('SET TRANSACTION READ WRITE')
        try: connection.exec_driver_sql(sql)
        except DBAPIError as error:
            require(getattr(error.orig, 'sqlstate', None) in codes, 'Wrong PG denial')
            connection.rollback()
            return True
        connection.rollback()
        raise RuntimeError('Forbidden SQL succeeded')


def exercise(app, connection, job):
    from app import create_app
    from app.config import Config
    from app.extensions import db
    from app.auth_service import hash_password
    from app.access_policy import active_policy, policy_claims
    from app.business_barrier import exclusive_barrier
    from app.models import Employee, Terminal, Wristband, Visit, OrderItem, WristbandChipBinding, WristbandScanSession
    from flask_jwt_extended import create_access_token
    urls={kind:make_url(os.environ[name]) for kind,name in (
        ('runtime','RUNTIME_DATABASE_URL'),('reset','RESET_DATABASE_URL'),('backup','RESET_BACKUP_DATABASE_URL'))}
    for url in [db.engine.url,*urls.values()]: require_isolated(url)
    require(len({(u.host,u.port or 5432,u.database) for u in [db.engine.url,*urls.values()]})==1,'Different clone endpoints')
    require(int(connection.exec_driver_sql('SHOW server_version_num').scalar_one())//10000==17,'Actual PG17 required')
    roles=prove_runtime_roles(connection)
    with exclusive_barrier(connection,job):
        require(connection.exec_driver_sql('SELECT maintenance_reset_id FROM business_state WHERE id=1').scalar_one()==job,
                'Clone maintenance owner differs')
        connection.exec_driver_sql('UPDATE business_state SET maintenance=false,maintenance_reset_id=NULL WHERE id=1')
        connection.commit()
    suffix=uuid.uuid4().hex
    password=secrets.token_urlsafe(32)
    with app.app_context():
        staff=Employee(username='scan-proof-'+suffix[:20], display_name='Isolated reader proof',
            password_hash=hash_password(password),role='cashier',allowed_channels=['desktop','web'])
        terminal=Terminal(code='scan-proof-'+suffix,name='Isolated reader proof')
        db.session.add_all([staff,terminal]);db.session.commit()
        employee_id,terminal_id=staff.id,terminal.id
        bands=Wristband.query.filter(Wristband.is_active.is_(True),Wristband.status=='available',
            Wristband.number.in_([f'{n:03}' for n in range(1,101)])).order_by(Wristband.number).all()
        bands=[band for band in bands if not Visit.query.filter_by(wristband_id=band.id,status='open').first()]
        require(len(bands)>=4,'Isolated proof needs four free current wristbands; production remains unchanged')
        band_ids=[band.id for band in bands[:4]]
        policy=active_policy()
        highest_ids=[policy.owner_id,*policy.mobile_employee_ids]
        mobile_id=next((identifier for identifier in highest_ids if (db.session.get(Employee,identifier) and
            db.session.get(Employee,identifier).is_active)),None)
        require(mobile_id,'Active highest administrator required for mobile clone read')

    class RuntimeConfig(Config):
        SECRET_KEY=secrets.token_urlsafe(48)
        JWT_SECRET_KEY=secrets.token_urlsafe(48)  # never valid against production
        SQLALCHEMY_DATABASE_URI=urls['runtime'].render_as_string(hide_password=False)
        SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping':True,'connect_args':{'options':'-c statement_timeout=25000 -c lock_timeout=15000'}}
        MAINTENANCE_PROCESS=False
        RESET_WORKER_ENABLED=False
        AUTO_CREATE_DB=False
        SMS_ENABLED=False
        SOCKETIO_ASYNC_MODE='threading'
    runtime_app=create_app(RuntimeConfig)
    def headers(channel='desktop',identifier=employee_id,session=None):
        with runtime_app.app_context():
            employee=db.session.get(Employee,identifier)
            claims=dict(policy_claims(employee,channel),terminal_id=terminal_id,
                session_version=employee.session_version,session_id=session or str(uuid.uuid4()))
            token=create_access_token(identifier,additional_claims=claims,expires_delta=timedelta(minutes=15))
            return {'Authorization':'Bearer '+token,'X-Business-Period':claims['business_period_id']}
    desktop=headers();web=headers('web');mobile=headers('mobile',mobile_id)
    def request(method,route,body=None,auth=None):
        with runtime_app.test_client() as client:
            response=client.open(route,method=method,json=body,headers=auth or desktop)
            return response.status_code,response.get_json()
    def bind(index,uid):
        return request('PUT','/api/wristband-reader/bindings/'+band_ids[index],{'chip_uid':uid,'version':0})
    uid='000'+str(uuid.uuid4().int)
    raced=parallel(lambda:bind(0,uid),lambda:bind(1,uid))
    require(sorted(status for status,_ in raced)==[200,409],'Concurrent UID uniqueness failed')
    with app.app_context(): bound_id=WristbandChipBinding.query.filter_by(chip_uid=uid).one().wristband_id
    require(bind(2,uid+'2')[0]==200 and bind(3,uid+'3')[0]==200,'Fixture binding failed')
    key=uuid.uuid4().hex
    payload={'chip_uid':uid,'link_mode':True,'idempotency_key':key}
    scans=parallel(lambda:request('POST','/api/wristband-reader/scan',payload),
                   lambda:request('POST','/api/wristband-reader/scan',payload))
    require(all(status==200 for status,_ in scans) and scans[0][1]['data']==scans[1][1]['data'],'Concurrent replay differs')
    first=scans[0][1]['data'];require(first['opened'] is True,'First scan did not open')
    with app.app_context():
        visits=Visit.query.filter_by(wristband_id=bound_id,status='open').all()
        require(len(visits)==1 and OrderItem.query.filter_by(visit_id=visits[0].id,status='active').count()==1,
            'Scan duplicated ticket or visit')
    retry=request('POST','/api/wristband-reader/scan',payload)
    require(retry[0]==200 and retry[1]['data']==first,'Exact replay failed')
    session=first['session']['id']
    next_payload={'chip_uid':uid+'2','link_mode':True,'session_id':session,'idempotency_key':uuid.uuid4().hex}
    require(request('POST','/api/wristband-reader/scan',next_payload,headers())[0]==403,'Relogin adopted old session')
    second=request('POST','/api/wristband-reader/scan',next_payload)
    require(second[0]==200 and len(second[1]['data']['session']['numbers'])==2,'Valid group did not link')
    with app.app_context():
        row=db.session.get(WristbandScanSession,session)
        row.expires_at=row.expires_at-timedelta(minutes=5);db.session.commit()
    expired=request('POST','/api/wristband-reader/scan',dict(next_payload,chip_uid=uid+'3',idempotency_key=uuid.uuid4().hex))
    require(expired[0]==200 and expired[1]['data']['session']['id']!=session,'Expired window was reused')
    require(request('POST','/api/wristband-reader/scan',payload,mobile)[0]==403,'Mobile opened wristband')
    require(request('GET','/api/wristband-reader/bindings',auth=mobile)[0]==403,'Mobile edited physical binding')
    reads={}
    for channel,auth,route in [('desktop',desktop,'/api/wristbands'),('web',web,'/api/wristbands'),('mobile',mobile,'/api/mobile/bootstrap')]:
        status,value=request('GET',route,auth=auth)
        require(status==200 and value['success'],'Authenticated read failed')
        rows=value['data']['wristbands'] if channel=='mobile' else value['data']
        view=[{key:row[key] for key in ('number','bath_area','visit_id','opened_at','amount')}
            for row in rows if row.get('visit_id') and (channel=='mobile' or row.get('status')=='in_use')]
        view.sort(key=lambda row:row['visit_id'])
        require({first['visit_id'],second[1]['data']['visit_id'],expired[1]['data']['visit_id']}
                <= {row['visit_id'] for row in view}, 'Clone read omitted newly opened wristbands')
        reads[channel]=hashlib.sha256(json.dumps(view,sort_keys=True).encode()).hexdigest()
    require(len(set(reads.values()))==1,'Three channels read different active orders')
    runtime=create_engine(urls['runtime'],hide_parameters=True);backup=create_engine(urls['backup'],hide_parameters=True)
    try:
        for table in NEW:
            require(denied(runtime,'DELETE FROM '+table,{'42501'}),'Runtime deleted binding/session evidence')
        require(denied(backup,'UPDATE wristband_chip_bindings SET version=version+1',{'25006'}),'Backup writable')
        require(denied(backup,'UPDATE wristband_chip_bindings SET version=version+1',{'42501'},read_write=True),'Backup ACL writable')
        with backup.connect() as check:
            for table in NEW:check.exec_driver_sql('SELECT count(*) FROM '+table)
        # Deliberately wrong period must be rejected by PG even without HTTP.
        require(denied(runtime,"UPDATE wristband_scan_sessions SET period_id='00000000-0000-0000-0000-000000000000'",{'P0001'}),
            'Database period guard missing')
        with exclusive_barrier(connection,job):
            connection.execute(text('UPDATE business_state SET maintenance=true,maintenance_reset_id=:job WHERE id=1'),{'job':job})
            connection.commit()
        require(denied(runtime,'UPDATE wristband_chip_bindings SET version=version+1',{'P0001'}),'Maintenance guard missing')
        return dict(pg17=True,isolated=True,uid_unique=True,scan_concurrency=True,replay_exact=True,login_isolation=True,
            period_guard=True,maintenance_barrier=True,backup_readable=True,runtime_roles=roles,
            compatibility=dict(scope='isolated authenticated endpoints; actual readers/devices not tested',shared_wristband_hashes=reads))
    finally:runtime.dispose();backup.dispose()
