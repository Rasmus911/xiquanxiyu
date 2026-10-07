"""A complete mixed catalog order, committed atomically with its revision."""
from .api.errors import ApiError
from .audit_service import write_audit
from .models import CatalogItem, SystemSetting

KEY = 'catalog_layout'


def _setting(session):
    # HTTP callers hold financial_lock; maintenance holds the exclusive barrier.
    row = session.query(SystemSetting).filter_by(key=KEY).with_for_update().first()
    if row is None:
        row = SystemSetting(key=KEY, value={'kind': 'mixed'}, description='全局加单排列')
        session.add(row)
        session.flush()
    return row


def quick_catalog(session):
    return session.query(CatalogItem).filter(CatalogItem.is_active.is_(True),
        CatalogItem.kind.in_(['service', 'product', 'package'])).order_by(CatalogItem.sort_order, CatalogItem.id).all()


def catalog_layout(session):
    row = _setting(session)
    return {'revision': row.version, 'ids': [item.id for item in quick_catalog(session)]}


def touch_catalog_layout(session):
    row = _setting(session)
    row.version += 1


def save_catalog_layout(session, employee, revision, ids):
    setting = _setting(session)
    rows = session.query(CatalogItem).filter(CatalogItem.is_active.is_(True),
        CatalogItem.kind.in_(['service', 'product', 'package'])).order_by(CatalogItem.id).with_for_update().all()
    expected = {row.id for row in rows}
    if (type(revision) is not int or revision != setting.version or not isinstance(ids, list)
            or any(not isinstance(id_, str) for id_ in ids) or len(ids) != len(set(ids)) or set(ids) != expected):
        raise ApiError('排列已改变或不完整，请刷新后重试', 409, 'CATALOG_LAYOUT_CONFLICT')
    before = {'revision': setting.version, 'ids': [row.id for row in sorted(rows, key=lambda row: (row.sort_order, row.id))]}
    by_id = {row.id: row for row in rows}
    for index, id_ in enumerate(ids):
        by_id[id_].sort_order = (index + 1) * 10
        by_id[id_].version += 1
    setting.version += 1
    after = {'revision': setting.version, 'ids': list(ids)}
    write_audit('catalog.layout', 'system_setting', setting.id, {'before': before, 'after': after},
        employee_id=employee.id, session=session)
    return after
