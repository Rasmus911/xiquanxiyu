"""Even SQLite development writers cannot race a physical account deletion."""
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError

from app import create_app
from app.api.errors import ApiError
from app.auth_service import employee_for_claims
from app.config import TestConfig
from app.extensions import db
from app.models import Employee, Terminal
from legacy_seed import seed_legacy_defaults


def test_mutation_principal_reserves_sqlite_writer_until_commit(tmp_path):
    class LockConfig(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'actor-lock.sqlite').as_posix()}"
    application = create_app(LockConfig)
    with application.app_context():
        db.create_all()
        seed_legacy_defaults()
        employee = Employee(username='isolated', display_name='隔离', role='cashier', password_hash='opaque')
        terminal = Terminal(code='LOCK-TEST', name='隔离')
        db.session.add_all([employee, terminal])
        db.session.commit()
        actor_id = employee.id
        claims = {'sub':actor_id, 'terminal_id':terminal.id, 'session_version':employee.session_version}
        competing = create_engine(LockConfig.SQLALCHEMY_DATABASE_URI, connect_args={'timeout':0})
        @event.listens_for(competing, 'connect')
        def competing_guard(raw, _record):
            raw.create_function('xiquan_reset_owner', 0, lambda: '')
        try:
            with application.test_request_context('/api/visits/isolated/items/batch', method='POST'):
                assert employee_for_claims(claims).id == actor_id
                assert db.session.connection().connection.driver_connection.in_transaction
                with competing.begin() as other:
                    with pytest.raises(OperationalError, match='locked'):
                        other.execute(text('DELETE FROM employees WHERE id=:id'), {'id':actor_id})
                db.session.rollback()
                with competing.begin() as other:
                    other.execute(text('DELETE FROM employees WHERE id=:id'), {'id':actor_id})
                with pytest.raises(ApiError) as error:
                    employee_for_claims(claims)
                assert error.value.code == 'ACCOUNT_DISABLED'
        finally:
            db.session.remove()
            competing.dispose()
            db.engine.dispose()
