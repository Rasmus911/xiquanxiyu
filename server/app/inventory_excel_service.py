"""Excel stocktake planning and atomic application under the financial lock."""
import base64
import binascii
import hashlib
import hmac
import json
import re
from decimal import Decimal

from flask import current_app
from flask_jwt_extended import get_jwt
from itsdangerous import BadSignature, URLSafeTimedSerializer, SignatureExpired

from .api.errors import ApiError
from .audit_service import write_audit
from .business_period import current_period_id
from .extensions import db
from .inventory_xlsx import MAX_FILE, parse_inventory_xlsx
from .models import StockImportPending, StockImportResolution, StockItem, new_uuid
from .serializers import stock_item_dict
from .stock_cost_basis import apply_stock_cost, plan_stock_cost, stock_cost_values
from .stock_cost_service import cost_amount
from .stock_service import change_balance, stock_quantity


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _signer(kind):
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='inventory-excel055-' + kind,
                                  signer_kwargs={'digest_method': hashlib.sha256})


def mapping_token(item):
    return _signer('mapping').dumps({'id': item.id, 'version': str(item.version)})


def _context(employee):
    claims = get_jwt()
    return dict(actor=employee.id, terminal=claims.get('terminal_id'), session=claims.get('jti'),
                period=current_period_id(), policy=claims.get('policy_version'))


def read_source(body):
    if (not isinstance(body.get('source_base64'), str) or len(body['source_base64']) > (MAX_FILE + 2) // 3 * 4 or
            not isinstance(body.get('source_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', body['source_sha256'])):
        raise ApiError('Excel文件或摘要无效', 400, 'INVALID_EXCEL_FILE')
    try: raw = base64.b64decode(body['source_base64'], validate=True)
    except (ValueError, binascii.Error): raise ApiError('Excel文件编码无效', 400, 'INVALID_EXCEL_FILE') from None
    if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), body['source_sha256']):
        raise ApiError('Excel文件已改变，请重新选择', 400, 'EXCEL_HASH_MISMATCH')
    try: return parse_inventory_xlsx(raw)
    except ValueError as error: raise ApiError(str(error), 400, 'INVALID_EXCEL_FILE') from None


def unresolved_rows():
    return StockImportPending.query.outerjoin(StockImportResolution,
        StockImportResolution.pending_id == StockImportPending.id).filter(StockImportResolution.id.is_(None)).order_by(
            StockImportPending.created_at, StockImportPending.id).all()


def pending_dict(row):
    return dict(id=row.id, name=row.name, quantity=f'{row.base_quantity:.3f}',
                package_cost=f'{row.package_cost:.2f}' if row.package_cost is not None else None,
                target_stock_item_id=row.target_stock_item_id, target_version=row.target_version,
                consumption_confirmed=row.consumption_confirmed,
                requires_password=bool(row.target_stock_item_id and
                    (db.session.get(StockItem, row.target_stock_item_id).unit_cost is not None)),
                source_row=row.source_row, source_sha256=row.source_sha256, created_at=row.created_at.isoformat())


def _row_plan(row, masters, pending, source_sha):
    name = row['name'].strip()
    if not name or len(name) > 120 or any(ord(c) < 32 for c in name): raise ApiError('商品名不能为空或超过120个字')
    quantity = stock_quantity(row['quantity'], zero=True)
    supplied_cost = cost_amount(row['package_cost']) if row['package_cost'] else None
    matched = None
    if row['stock_item_id']:
        matched = next((item for item in masters if item.id == row['stock_item_id']), None)
        if matched is None: raise ApiError('库存项目ID不存在，不能按名称自动改写其他条目')
        try: token = _signer('mapping').loads(row['mapping_token'])
        except BadSignature: raise ApiError('隐藏匹配信息已被修改，请重新导出或使用三列外部表格') from None
        if token != {'id': matched.id, 'version': row['source_version']}:
            raise ApiError('库存ID或记录版本与导出校验码不一致')
    else:
        same = [item for item in masters if item.name == name]
        if len(same) > 1: raise ApiError('存在同名库存，请使用应用导出的含隐藏ID模板')
        if same: matched = same[0]
    if matched and not matched.is_active: raise ApiError('库存已归档，不能由Excel自动恢复')
    if matched and any(item.id != matched.id and item.name == name for item in masters):
        raise ApiError('修改后的名称与其他库存项目冲突')
    result = dict(row_number=row['row_number'], name=name, target_quantity=f'{quantity:.3f}',
                  supplied_package_cost=f'{supplied_cost:.2f}' if supplied_cost is not None else None,
                  requires_consumption_confirmation=False, password_required=False)
    if matched is None or matched.base_unit == '原销售单位':
        same = [item for item in pending if item.name == name]
        if same:
            if len(same) == 1 and same[0].source_sha256 == source_sha and same[0].source_row == row['row_number']:
                return dict(result, action='already_pending', pending_id=same[0].id)
            raise ApiError('同名条目已在待补资料中，请先完成或取消该条目')
        recorded = StockImportPending.query.filter_by(source_sha256=source_sha, source_row=row['row_number']).first()
        if recorded: raise ApiError('该来源行已完成或取消，请重新导出当前库存后修改')
        if matched:
            original = Decimal(matched.stock_quantity); delta = quantity - original
            return dict(result, action='needs_units', stock_item_id=matched.id, version=matched.version,
                current_quantity=f'{original:.3f}', base_unit='待核实基本单位', package_unit='待补资料',
                requires_consumption_confirmation=original > 0 and delta < 0 and -delta * 4 >= original,
                decrease_percentage=f'{((-delta / original) * 100):.2f}' if original > 0 and delta < 0 else None)
        return dict(result, action='new', base_unit='待补资料', package_unit='待补资料')
    costs = stock_cost_values(matched)
    # An unchanged rounded export must not alter a precise existing base cost.
    cost_body = {'reference_cost': str(supplied_cost), 'cost_basis': 'package' if matched.package_unit else 'base'} if (
        supplied_cost is not None and (costs['package_cost'] is None or supplied_cost != Decimal(costs['package_cost']))) else {}
    plan = plan_stock_cost(matched, cost_body)
    original = Decimal(matched.stock_quantity)
    delta = quantity - original
    cost_changed = bool(cost_body)
    requires = original > 0 and delta < 0 and -delta * 4 >= original
    return dict(result, action='update' if delta or name != matched.name or cost_changed else 'unchanged',
        stock_item_id=matched.id, version=matched.version, current_name=matched.name,
        current_quantity=f'{original:.3f}', quantity_delta=f'{delta:.3f}', base_unit=matched.base_unit,
        package_unit=matched.package_unit or matched.base_unit, units_per_package=f'{matched.units_per_package:.3f}',
        current_package_cost=costs['package_cost'], target_package_cost=f'{supplied_cost:.2f}' if supplied_cost is not None else costs['package_cost'],
        cost_body=cost_body, password_required=plan['password_required'],
        requires_consumption_confirmation=requires,
        decrease_percentage=f'{((-delta / original) * 100):.2f}' if original > 0 and delta < 0 else None,
        template_changed=bool(row['source_version'] and row['source_version'] != str(matched.version)))


def build_preview(employee, body, *, lock=False):
    rows = read_source(body)
    query = StockItem.query.order_by(StockItem.id)
    masters = query.with_for_update().all() if lock else query.all()
    pending = unresolved_rows()
    results, errors, names, ids = [], [], set(), set()
    for row in rows:
        try:
            name = row['name'].strip()
            if name in names or (row['stock_item_id'] and row['stock_item_id'] in ids):
                raise ApiError('同一文件的商品名或项目ID重复')
            names.add(name)
            if row['stock_item_id']: ids.add(row['stock_item_id'])
            value = _row_plan(row, masters, pending, body['source_sha256'])
            results.append(value)
        except ApiError as error:
            errors.append(dict(row_number=row['row_number'], name=row['name'], message=error.message))
    value = dict(source_sha256=body['source_sha256'], rows=results, errors=errors,
        snapshot_digest=_digest([stock_item_dict(item) for item in masters] + [pending_dict(item) for item in pending]),
        context=_context(employee))
    value['preview_digest'] = _digest(value)
    value['preview_token'] = _signer('preview').dumps({'digest': value['preview_digest'], 'context': value['context']})
    value['requires_password'] = any(row.get('password_required') for row in results)
    return value


def apply_preview(employee, body):
    try: authorized = _signer('preview').loads(body.get('preview_token', ''), max_age=600)
    except (BadSignature, SignatureExpired):
        raise ApiError('导入预览已过期或无效，请重新预览', 409, 'EXCEL_PREVIEW_STALE') from None
    if authorized.get('context') != _context(employee):
        raise ApiError('导入预览不属于本次登录，请重新预览', 409, 'EXCEL_PREVIEW_STALE')
    preview = build_preview(employee, body, lock=True)
    if not hmac.compare_digest(str(authorized.get('digest', '')), preview['preview_digest']):
        raise ApiError('库存已被其他操作修改，请重新预览', 409, 'EXCEL_PREVIEW_STALE')
    if preview['errors']: raise ApiError('请先修正所有错误行，尚未导入任何数据', 400, 'EXCEL_ROWS_INVALID')
    confirmed = body.get('confirmed_rows')
    if (not isinstance(confirmed, list) or any(type(row) is not int for row in confirmed) or
            len(confirmed) != len(set(confirmed)) or set(confirmed) - {row['row_number'] for row in preview['rows']}):
        raise ApiError('异常数量确认行号无效', 400, 'EXCEL_CONFIRMATION_REQUIRED')
    required = {row['row_number'] for row in preview['rows'] if row['requires_consumption_confirmation']}
    if not required <= set(confirmed): raise ApiError('是否是真的消耗了这么多？请确认减少25%或以上的条目', 400, 'EXCEL_CONFIRMATION_REQUIRED')
    if preview['requires_password']:
        from .auth_service import verify_sensitive_password
        verify_sensitive_password(employee, body.get('password'))  # before ANY business mutation
    batch = new_uuid()
    counts = dict(updated=0, pending=0, unchanged=0)
    for row in preview['rows']:
        if row['action'] in {'unchanged', 'already_pending'}:
            counts['unchanged'] += 1; continue
        if row['action'] in {'new', 'needs_units'}:
            pending = StockImportPending(name=row['name'], base_quantity=Decimal(row['target_quantity']),
                package_cost=Decimal(row['supplied_package_cost']) if row['supplied_package_cost'] is not None else None,
                source_sha256=body['source_sha256'], source_row=row['row_number'], created_by_id=employee.id)
            pending.target_stock_item_id = row.get('stock_item_id')
            pending.target_version = row.get('version')
            pending.consumption_confirmed = row['row_number'] in required
            db.session.add(pending); db.session.flush()
            write_audit('stock.excel_pending', 'stock_import_pending', pending.id, pending_dict(pending))
            counts['pending'] += 1; continue
        master = db.session.get(StockItem, row['stock_item_id'])
        before = stock_item_dict(master)
        delta = Decimal(row['quantity_delta'])
        if delta:
            change_balance(master, delta, employee, 'adjust', 'Excel人工盘点',
                           reference_type='stock_excel', reference_id=batch)
        master.name = row['name']
        if row['cost_body']: apply_stock_cost(master, plan_stock_cost(master, row['cost_body']))
        if not delta: master.version += 1
        write_audit('stock.excel_update', 'stock_item', master.id, dict(before=before, after=stock_item_dict(master),
            source_sha256=body['source_sha256'], source_row=row['row_number'], batch_id=batch,
            abnormal_consumption_confirmed=row['row_number'] in required))
        counts['updated'] += 1
    write_audit('stock.excel_apply', 'stock_excel', batch, dict(source_sha256=body['source_sha256'],
        preview_digest=preview['preview_digest'], confirmed_rows=sorted(confirmed), **counts))
    return dict(batch_id=batch, **counts)
