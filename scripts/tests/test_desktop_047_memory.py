"""Resource gate must measure restore RAM after releasing the old API's RAM."""
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'deploy/cloud/scripts'))
import desktop_047_deploy as deploy
from stock_deploy import require_resource_budget, MIB


def driver(monkeypatch, after_stop=870, changed_image=False):
    instance = object.__new__(deploy.Desktop047)
    instance.api_stop_started = False
    running = {'value': True}
    events = []
    old = {'Id':'original-api-id','Image':'sha256:old', 'Config':{'Env':['fixture=only']}}
    instance.phase = lambda name: events.append(name)
    def compose(*args):
        assert args == ('stop','api')
        events.append('stop'); running['value'] = False
    instance.compose = compose
    def check(phase, include_restore=False):
        events.append(('budget',running['value'],include_restore))
        return require_resource_budget((758 if running['value'] else after_stop)*MIB,
                                       28*1024**3,include_restore=include_restore)
    monkeypatch.setattr(deploy,'check_resources',check)
    def run(args):
        if args == ['docker','inspect','original-api-id']:
            return json.dumps([{**old,'Image':'sha256:different' if changed_image else old['Image'],
                                'State':{'Running':False}}])
        if args == ['docker','start','original-api-id']:
            events.append('restore-original'); running['value'] = True
            return 'original-api-id'
        raise AssertionError('Unexpected external mutation: '+repr(args))
    monkeypatch.setattr(deploy,'run',run)
    monkeypatch.setattr(deploy,'fresh_state',lambda:events.append('read-only-unchanged-schema'))
    monkeypatch.setattr(deploy,'wait_healthy',lambda name,timeout=180:events.append(('healthy',name)))
    return instance,old,events


def test_758_mib_host_releases_old_api_ram_before_full_768_mib_gate(monkeypatch):
    instance,old,events=driver(monkeypatch)
    instance.stop_writes_with_restore_budget(old)
    assert ('budget',False,True) in events
    assert events.index('stop') < events.index(('budget',False,True))
    assert 'restore-original' not in events
    assert instance.api_stop_started is True


def test_post_stop_shortage_restores_exact_old_api_without_touching_database(monkeypatch):
    instance,old,events=driver(monkeypatch,after_stop=700)
    with pytest.raises(deploy.DeploymentError,match='700.*768'):
        instance.stop_writes_with_restore_budget(old)
    assert 'restore-original' in events and ('healthy','xiquan-api-1') in events
    assert instance.api_stop_started is False


def test_post_stop_shortage_never_restarts_replaced_container_identity(monkeypatch):
    instance,old,events=driver(monkeypatch,after_stop=700,changed_image=True)
    with pytest.raises(deploy.DeploymentError,match='identity'):
        instance.stop_writes_with_restore_budget(old)
    assert 'restore-original' not in events


def test_real_deploy_reaches_claim_with_758_mib_while_old_api_running(monkeypatch, tmp_path):
    """Exercise deploy() ordering, not only the new helper in isolation."""
    instance, old, events = driver(monkeypatch)
    instance.normal_env = dict.fromkeys(('DATABASE_URL', 'SECRET_KEY', 'JWT_SECRET_KEY', 'AUDIT_HMAC_KEY'), 'fixture')
    instance.env = {}
    instance.stage = tmp_path / 'stage'
    instance.report = {'source_commit': 'fixture'}
    instance.protected = lambda: events.append('protected-read-only')
    instance.build = lambda image: events.append('offline-build')
    cloud = tmp_path / 'cloud'
    cloud.mkdir()
    # Fixtures are configuration fingerprints only, never real credentials.
    monkeypatch.setattr(deploy, 'CLOUD', cloud)
    monkeypatch.setattr(deploy, 'BACKUPS', tmp_path)
    monkeypatch.setattr(deploy, 'digest_file', lambda path: 'fixture-hash')
    old.update(Config={'Env': [key + '=fixture' for key in instance.normal_env]},
               State={'Running': True, 'Health': {'Status': 'healthy'}},
               NetworkSettings={'Networks': {'backend': {}}})
    postgres = {**old, 'Id': 'postgres-id', 'Image': 'sha256:postgres'}

    def run(args):
        if args[:2] == ['docker', 'inspect']:
            assert args[2:] == ['xiquan-api-1', 'xiquan-postgres-1']
            return json.dumps([old, postgres])
        if args[:3] == ['docker', 'network', 'inspect']:
            return json.dumps([{'Internal': True}])
        if args[:2] == ['docker', 'ps']:
            return json.dumps({'ID': 'original-api-id'})
        if args[:3] == ['docker', 'network', 'create']:
            return 'isolated-network'
        raise AssertionError('Unexpected external command: ' + repr(args))

    class ReachedClaim(Exception):
        pass

    def guard(mode):
        if mode == 'claim':
            events.append('claim')
            raise ReachedClaim
        assert mode == 'inspect'
        return {}

    monkeypatch.setattr(deploy, 'run', run)
    instance.guard = guard
    with pytest.raises(ReachedClaim):
        instance.deploy()
    assert events.index('stop') < events.index(('budget', False, True)) < events.index('claim')
    assert ('budget', True, True) not in events
