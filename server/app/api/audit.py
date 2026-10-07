from datetime import datetime, timezone

from flask import Blueprint, request

from ..audit_service import lock_audit_chain, sign_evidence, verify_audit_chain, write_audit
from ..auth_service import require_permission
from ..extensions import db
from ..financial_integrity import check_financial_integrity
from ..models import AuditLog, Employee, Terminal, utcnow
from ..serializers import ACTION_LABELS, audit_dict
from .errors import ApiError, success

bp = Blueprint("audit", __name__, url_prefix="/audit")


def filtered_audit_query():
    query = AuditLog.query
    if request.args.get("action"):
        action_keyword = request.args["action"].strip()
        matching_actions = [code for code, label in ACTION_LABELS.items() if action_keyword in label]
        query = query.filter(
            db.or_(AuditLog.action.ilike(f"%{action_keyword}%"), AuditLog.action.in_(matching_actions))
        )
    if request.args.get("employee"):
        employee_keyword = request.args["employee"].strip()
        query = query.outerjoin(Employee, AuditLog.employee_id == Employee.id).filter(
            db.or_(
                AuditLog.context["employee_username"].as_string().ilike(f"%{employee_keyword}%"),
                db.and_(AuditLog.integrity_version == 1, Employee.username.ilike(f"%{employee_keyword}%")),
            )
        )
    if request.args.get("terminal"):
        term = request.args["terminal"].strip()
        query = query.outerjoin(Terminal, AuditLog.terminal_id == Terminal.id).filter(
            db.or_(
                AuditLog.context["terminal_code"].as_string().ilike(f"%{term}%"),
                AuditLog.context["terminal_name"].as_string().ilike(f"%{term}%"),
                db.and_(AuditLog.integrity_version == 1, Terminal.code.ilike(f"%{term}%")),
            )
        )
    if request.args.get("request_id"):
        query = query.filter(AuditLog.request_id == request.args["request_id"].strip())
    if request.args.get("keyword"):
        word = request.args["keyword"].strip()
        query = query.filter(
            db.or_(AuditLog.entity_id.ilike(f"%{word}%"), db.cast(AuditLog.details, db.String).ilike(f"%{word}%"))
        )
    for field, is_start in (("start", True), ("end", False)):
        if request.args.get(field):
            try:
                value = datetime.fromisoformat(request.args[field])
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
            except ValueError:
                raise ApiError("操作记录时间格式无效") from None
            query = query.filter(AuditLog.created_at >= value if is_start else AuditLog.created_at <= value)
    return query


def audit_rows(rows):
    employee_ids = {row.employee_id for row in rows if row.employee_id}
    terminal_ids = {row.terminal_id for row in rows if row.terminal_id}
    employees = (
        {row.id: row for row in Employee.query.filter(Employee.id.in_(employee_ids)).all()} if employee_ids else {}
    )
    terminals = (
        {row.id: row for row in Terminal.query.filter(Terminal.id.in_(terminal_ids)).all()} if terminal_ids else {}
    )
    return [audit_dict(row, employees.get(row.employee_id), terminals.get(row.terminal_id)) for row in rows]


@bp.get("")
@require_permission("audit:read")
def list_audit():
    try:
        page = max(int(request.args.get("page", 1)), 1)
        page_size = min(max(int(request.args.get("page_size", 30)), 1), 100)
    except ValueError:
        raise ApiError("分页参数格式无效") from None
    query = filtered_audit_query()
    result = query.order_by(AuditLog.chain_index.desc()).paginate(page=page, per_page=page_size, error_out=False)
    return success(
        {
            "items": audit_rows(result.items),
            "total": result.total,
            "page": page,
            "page_size": page_size,
        }
    )


@bp.get("/verify")
@require_permission("audit:read")
def verify_chain():
    lock_audit_chain()
    valid, broken_at = verify_audit_chain()
    checkpoint_valid = None
    if request.args.get("checkpoint_index"):
        try:
            index = int(request.args["checkpoint_index"])
        except ValueError:
            raise ApiError("证据检查点格式无效") from None
        record = AuditLog.query.filter_by(chain_index=index).first()
        checkpoint_valid = bool(record and record.current_hash == request.args.get("checkpoint_hash"))
    return success({"valid": valid, "broken_at": broken_at, "checkpoint_valid": checkpoint_valid})


@bp.get("/evidence")
@require_permission("audit:read")
def export_evidence():
    lock_audit_chain()
    rows = filtered_audit_query().order_by(AuditLog.chain_index).limit(5001).all()
    if len(rows) > 5000:
        raise ApiError("单次证据导出最多 5000 条，请缩小时间范围")
    valid, broken_at = verify_audit_chain()
    tail = AuditLog.query.order_by(AuditLog.chain_index.desc()).first()
    document = {
        "schema_version": 1,
        "exported_at": utcnow().isoformat(),
        "filters": {
            key: request.args[key]
            for key in ("start", "end", "employee", "action", "terminal", "request_id", "keyword")
            if request.args.get(key)
        },
        "verification": {"valid": valid, "broken_at": broken_at},
        "checkpoint": {"chain_index": tail.chain_index if tail else 0, "hash": tail.current_hash if tail else "0" * 64},
        "records": audit_rows(rows),
    }
    document["signature"] = sign_evidence(document)
    write_audit(
        "audit.export",
        "audit",
        None,
        {"count": len(rows), "filters": document["filters"], "checkpoint": document["checkpoint"]},
    )
    db.session.commit()
    return success(document)


@bp.get("/finance-integrity")
@require_permission("audit:read")
def finance_integrity():
    lock_audit_chain()
    result = check_financial_integrity()
    write_audit("audit.finance_check", "audit", None, result)
    db.session.commit()
    return success(result)
