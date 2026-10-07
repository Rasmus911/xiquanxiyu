"""Database-authoritative business scope. Archive contexts are trusted, read-only code."""
from contextlib import contextmanager
from contextvars import ContextVar

from flask import has_request_context, request
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import Alias, SelectBase

from .extensions import db
from .models import BusinessPeriod, BusinessStateModel, PeriodMixin

INITIAL_PERIOD_ID = '00000000-0000-0000-0000-000000000001'
_archive_scope = ContextVar('business_archive_scope', default=False)
_registered = False


def ensure_business_state(session):
    with session.no_autoflush:
        state = session.get(BusinessStateModel, 1, populate_existing=True)
        if state is None:
            period = session.get(BusinessPeriod, INITIAL_PERIOD_ID)
            if period is None:
                session.add(BusinessPeriod(id=INITIAL_PERIOD_ID))
                session.flush()
            state = BusinessStateModel(id=1, period_id=INITIAL_PERIOD_ID)
            session.add(state)
            session.flush()
        return state


def current_period_id():
    return ensure_business_state(db.session).period_id


def read_period_id():
    scope = _archive_scope.get()
    if scope is not False:
        return scope
    authenticated = request.environ.get('xiquan.authenticated_read_period') if has_request_context() else None
    return authenticated or current_period_id()


def bind_authenticated_read_period(claims):
    """Pin only after JWT/session/header validation, for this HTTP request alone."""
    if (has_request_context() and request.method in {'GET', 'HEAD'}
            and request.path.startswith('/api/') and claims.get('business_period_id')):
        request.environ.setdefault('xiquan.authenticated_read_period', claims['business_period_id'])


def validate_read_response(response):
    """Discard materialized responses whose authenticated period crossed a cutover.

    Use a fresh connection: SQLite WAL/explicit read transactions (and PostgreSQL
    repeatable-read transactions) may otherwise keep returning an obsolete state.
    Ordinary business queries remain pinned even with sqlite3's legacy SELECT
    behavior, which does not start a database transaction. This check is the read's
    final linearization point; a subsequent cutover cannot change its loaded data.
    """
    expected = request.environ.get('xiquan.authenticated_read_period')
    if not expected or response.status_code >= 400:
        return response
    with db.engine.connect() as connection:
        current = connection.execute(select(BusinessStateModel.period_id).where(
            BusinessStateModel.id == 1)).scalar_one_or_none()
    if current != expected:
        from flask import current_app, g
        response.set_data(current_app.json.dumps({
            'success': False, 'message': '经营期已变更，请重新登录',
            'error': {'code': 'BUSINESS_PERIOD_CHANGED', 'details': None},
            'request_id': getattr(g, 'request_id', None),
        }))
        response.status_code = 409
        response.mimetype = 'application/json'
    return response


@contextmanager
def archive_read(period_id=None):
    # Do not turn pending writes into an archive operation during autoflush.
    if db.session.new or db.session.dirty or db.session.deleted:
        raise ValueError('archive read-only context requires a clean session')
    token = _archive_scope.set(period_id)
    try:
        yield
    finally:
        _archive_scope.reset(token)
        # No archived entity may leak through an identity-map hit after this context.
        db.session.expire_all()


def business_state_data(employee=None, channel=None):
    from .access_policy import effective_permissions, is_owner, session_permissions
    from .employee_access import session_ui
    from flask_jwt_extended import get_jwt

    state = ensure_business_state(db.session)
    ui = {'ui_pages': [], 'capabilities': {}}
    if employee is not None:
        if channel is not None:
            permissions = session_permissions(employee, channel)
        elif has_request_context():
            # get_jwt only exposes claims from a verified JWT decorator. Login
            # passes its explicitly verified channel, never a header/query hint.
            claims = get_jwt()
            channel = claims.get('client_channel')
            permissions = effective_permissions(employee, claims)
        else:
            permissions = set()
        ui = session_ui(employee, channel, permissions)
    return dict(period_id=state.period_id, business_revision=state.business_revision,
                policy_version=state.policy_version, maintenance=state.maintenance,
                owner_reset_allowed=is_owner(employee), **ui)


def _period_models():
    return tuple(mapper.class_ for mapper in db.Model.registry.mappers
                 if issubclass(mapper.class_, PeriodMixin))


def _scope_nodes(root, authorized_aliases=()):
    """Visit one SELECT occurrence, never borrowing provenance from a nested SELECT."""
    pending = [root]
    while pending:
        node = pending.pop()
        if node is not root and isinstance(node, SelectBase):
            continue
        yield node
        if isinstance(node, Alias) and node in authorized_aliases:
            continue  # Its underlying table is part of this mapped alias occurrence.
        pending.extend(node.get_children())


def _validate_query_scopes(statement, names):
    all_nodes = tuple(visitors.iterate(statement))
    for node in all_nodes:
        # SQL strings cannot carry mapper provenance. Inspect the entire tree,
        # including projections, predicates, nested statements and literal columns.
        if isinstance(node, TextClause) or (getattr(node, 'is_literal', False)
                                           and getattr(node, 'name', None) != '*'):
            raise ValueError('Use scoped ORM expressions, not embedded textual SQL')
    for scope in (node for node in all_nodes if isinstance(node, SelectBase)):
        entities = [node._annotations['parententity'] for node in _scope_nodes(scope)
                    if node._annotations.get('parententity') is not None]
        selectables = {inspect(entity).selectable for entity in entities}
        for node in _scope_nodes(scope, selectables):
            if getattr(node, '__visit_name__', None) == 'table' and node.name in names:
                if node not in selectables:
                    raise ValueError('Use scoped ORM entities in each query scope')
            if isinstance(node, Alias) and node not in selectables:
                base = node.element
                while isinstance(base, Alias):
                    base = base.element
                if getattr(base, 'name', None) in names:
                    raise ValueError('Use scoped ORM aliases, not raw Core business aliases')


def _scope_query(execute_state):
    statement = execute_state.statement
    if _archive_scope.get() is not False and not execute_state.is_select:
        raise ValueError('archive read-only context forbids writes and text SQL')
    models = _period_models()
    names = {model.__tablename__ for model in models}
    if isinstance(statement, TextClause):
        # Text SQL cannot be safely rewritten. Application callers use scoped ORM.
        # Engine/connection SQL is reserved for migrations, guards, and trusted services.
        import re
        if any(re.search(r'\b' + name + r'\b', statement.text, re.I) for name in names):
            raise ValueError('Use scoped ORM for business data')
        return
    touched = any(getattr(node, 'name', None) in names for node in visitors.iterate(statement))
    _validate_query_scopes(statement, names)
    if touched and (not execute_state.is_orm_statement or not execute_state.is_select):
        raise ValueError('Use scoped ORM for business data; bulk writes are forbidden')
    if not execute_state.is_select or not execute_state.is_orm_statement:
        return
    period_id = read_period_id() if touched else None
    if touched and period_id is not None:
        if execute_state.is_column_load:
            # SQLAlchemy refresh/expire loaders bypass with_loader_criteria.
            # Their bound mapper is authoritative; add the predicate directly.
            mapper = execute_state.bind_mapper
            if mapper is not None and issubclass(mapper.class_, PeriodMixin):
                statement = statement.where(mapper.local_table.c.period_id == period_id)
        for model in models:
            statement = statement.options(with_loader_criteria(
                model, model.period_id == period_id, include_aliases=True))
        execute_state.statement = statement


def _protect_flush(session, _context, _instances):
    changed = session.new | session.dirty | session.deleted
    if _archive_scope.get() is not False and changed:
        raise ValueError('archive read-only context forbids writes')
    business = [row for row in changed if isinstance(row, PeriodMixin)]
    if not business:
        return
    # Use the connection to avoid a recursive autoflush while inspecting current state.
    period_id = session.connection().execute(select(BusinessStateModel.period_id)
                                            .where(BusinessStateModel.id == 1)).scalar_one()
    for row in business:
        state = inspect(row)
        if row not in session.new:
            if state.attrs.period_id.history.has_changes():
                raise ValueError('经营期归属不可修改')
            # Check stored attribution before loading any expired attributes.
            # This also produces a clear write rejection for cached old entities.
            table = state.mapper.local_table
            stored_period = session.connection().execute(select(table.c.period_id).where(
                *(column == value for column, value in zip(state.mapper.primary_key, state.identity, strict=True))
            )).scalar_one_or_none()
            if stored_period != period_id:
                raise ValueError('该记录属于已归档经营期')
        if row in session.new and row.period_id is None:
            row.period_id = period_id
        if row.period_id != period_id:
            raise ValueError('该记录属于已归档经营期')
    tables = {model.__tablename__ for model in _period_models()}
    for row in business:
        if row in session.deleted:
            continue
        for fk in inspect(type(row)).local_table.foreign_keys:
            if fk.column.table.name not in tables:
                continue
            value = getattr(row, fk.parent.name)
            if value is None:
                continue
            pending = next((candidate for candidate in session.new
                            if isinstance(candidate, PeriodMixin)
                            and candidate.__tablename__ == fk.column.table.name
                            and getattr(candidate, fk.column.name) == value), None)
            related_period = pending.period_id if pending else session.connection().execute(
                select(fk.column.table.c.period_id).where(fk.column == value)).scalar_one_or_none()
            if related_period != period_id:
                raise ValueError('跨经营期关联被拒绝')


def register_period_hooks(app):
    global _registered
    if not _registered:
        event.listen(Session, 'do_orm_execute', _scope_query)
        event.listen(Session, 'before_flush', _protect_flush)
        _registered = True
