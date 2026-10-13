"""Proof must use actual per-channel endpoints; phone permissions stay limited."""
import ast
import hashlib
import importlib.util
import json
from datetime import timedelta
from pathlib import Path

import pytest
from flask_jwt_extended import create_access_token

from app.access_policy import active_policy, policy_claims, session_permissions
from app.extensions import db
from app.models import Employee, Terminal, Wristband, Visit

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('proof_channel_recovery', ROOT / 'scripts/lib/desktop-051-backup-resume.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


def run_channel_reads(app):
    original = (ROOT / 'deploy/cloud/scripts/desktop_051_pgproof.py').read_bytes()
    tree = ast.parse(recovery.proof_source_in_authenticated_context(original))
    exercise = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'exercise')
    first = next(i for i, n in enumerate(exercise.body[-1].body)
                 if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'reads' for t in n.targets))
    segment = exercise.body[-1].body[first:first+3]
    module = ast.fix_missing_locations(ast.Module(body=segment, type_ignores=[]))
    def require(ok, message):
        if not ok:
            raise RuntimeError(message)
    scope = dict(runtime_app=app, db=db, Employee=Employee, Visit=Visit, Wristband=Wristband,
        active_policy=active_policy, policy_claims=policy_claims, create_access_token=create_access_token,
        terminal_id=Terminal.query.filter_by(code='ENTRY-TEST').one().id,
        timedelta=timedelta, hashlib=hashlib, json=json, require=require)
    exec(compile(module, '<real-proof-channel-reads>', 'exec'), scope)
    return scope['reads']


def test_proof_compares_shared_active_bands_using_real_mobile_endpoint(app, client, strict_owner_session):
    band = Wristband.query.order_by(Wristband.number).first()
    opened = client.post('/api/wristbands/' + band.id + '/open', headers=strict_owner_session['headers'], json={})
    assert opened.status_code == 201
    owner = db.session.get(Employee, strict_owner_session['owner_id'])
    assert 'visit:read' not in session_permissions(owner, 'mobile')
    reads = run_channel_reads(app)
    assert set(reads) == {'desktop-old', 'desktop-new', 'web', 'mobile-1.2.9'}
    assert len(set(reads.values())) == 1
    assert 'visit:read' not in session_permissions(db.session.get(Employee, owner.id), 'mobile')


def test_shared_read_proof_detects_a_missing_mobile_band(app, client, strict_owner_session):
    band = Wristband.query.order_by(Wristband.number).first()
    assert client.post('/api/wristbands/' + band.id + '/open',
        headers=strict_owner_session['headers'], json={}).status_code == 201
    def remove_phone_band(response):
        from flask import request
        if request.path == '/api/mobile/bootstrap' and response.status_code == 200:
            body = response.get_json()
            body['data']['wristbands'] = []
            response.set_data(json.dumps(body))
        return response
    app.after_request_funcs.setdefault(None, []).append(remove_phone_band)
    with pytest.raises(RuntimeError, match='same data|active visits'):
        run_channel_reads(app)
