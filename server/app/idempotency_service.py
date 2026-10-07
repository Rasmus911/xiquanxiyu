import hashlib
import json

from flask import request
from flask_jwt_extended import get_jwt

from .api.errors import ApiError
from .extensions import db
from .models import IdempotencyRecord


def idempotency_record_key(endpoint: str, actor_id: str, raw_key: str) -> str:
    from .access_policy import policy_enforced
    from .business_period import current_period_id
    if policy_enforced():
        value = json.dumps([endpoint, actor_id, get_jwt().get('client_channel'),
                            current_period_id(), raw_key], ensure_ascii=False).encode('utf-8')
    else:
        value = f"{endpoint}:{actor_id}:{raw_key}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def financial_request_key(endpoint, actor_id, raw_key):
    """Namespace new financial unique-column values; existing history is untouched."""
    from .access_policy import policy_enforced
    raw_key = str(raw_key)
    if len(raw_key) > 100:
        raise ApiError('请求编号过长')
    return idempotency_record_key(endpoint, actor_id, raw_key) if policy_enforced() else raw_key


def request_fingerprint(body):
    sanitized = {key: value for key, value in body.items() if key != "idempotency_key"}
    return hashlib.sha256(json.dumps(sanitized, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def idempotency_lookup(endpoint: str, actor_id: str, raw_key: str):
    if len(raw_key) > 100:
        raise ApiError("请求编号过长")
    key = idempotency_record_key(endpoint, actor_id, raw_key)
    record = db.session.get(IdempotencyRecord, key)
    if record and record.response_body.get("_request_hash"):
        if record.response_body["_request_hash"] != request_fingerprint(request.get_json(silent=True) or {}):
            raise ApiError("同一请求编号不能用于不同的操作内容，请刷新后重试", 409, "IDEMPOTENCY_CONFLICT")
    return record


def guard_financial_request(endpoint, employee, raw_key, body, original=None, owner_id=None):
    if original and owner_id != employee.id:
        raise ApiError("请求编号已被其他员工使用", 409, "IDEMPOTENCY_CONFLICT")
    record = idempotency_lookup(endpoint, employee.id, str(raw_key))
    if not record and not original:
        idempotency_store(idempotency_record_key(endpoint, employee.id, str(raw_key)), endpoint, 200, {})


def idempotency_store(
    key: str,
    endpoint: str,
    status: int,
    body: dict,
) -> IdempotencyRecord:
    record = IdempotencyRecord(
        key=key,
        endpoint=endpoint,
        response_status=status,
        response_body={**body, "_request_hash": request_fingerprint(request.get_json(silent=True) or {})},
    )
    db.session.add(record)
    return record
