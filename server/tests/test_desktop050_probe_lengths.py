"""The isolated PostgreSQL probe must respect the real production column widths."""
import importlib
import sys
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'deploy/cloud/scripts'))


def exercise_until_receipt_fixture(guard, app, monkeypatch):
    from app.extensions import db
    from app.models import Terminal, Wristband

    registration = importlib.import_module('desktop_049_guard')
    monkeypatch.setattr(registration, 'exercise', lambda *args: {})
    original_require = guard.require_isolated
    monkeypatch.setattr(guard, 'require_isolated',
                        lambda url: None if url.drivername == 'sqlite' else original_require(url))
    monkeypatch.setattr(guard, 'roles', lambda: {
        'runtime': make_url('postgresql://test@xiquan-operations-restore-test/operations_restore')})
    monkeypatch.setattr(guard, 'create_engine', lambda *args, **kwargs: object())

    class FixtureChecked(Exception):
        pass

    def check_widths(session, flush_context, instances):
        bands = [row for row in session.new if isinstance(row, Wristband)]
        if not bands:
            return
        for row in session.new:
            if isinstance(row, (Terminal, Wristband)):
                for column in row.__table__.columns:
                    limit = getattr(column.type, 'length', None)
                    value = getattr(row, column.name)
                    if limit and isinstance(value, str):
                        assert len(value) <= limit, (column.name, len(value), limit)
        assert len(bands[0].number) <= 30
        raise FixtureChecked()

    session_class = db.session.session_factory.class_
    event.listen(session_class, 'before_flush', check_widths)
    try:
        with pytest.raises(FixtureChecked):
            guard.exercise(app, object(), '00000000-0000-0000-0000-000000000001')
    finally:
        event.remove(session_class, 'before_flush', check_widths)
        db.session.rollback()


def test_receipt_rehearsal_band_fits_postgresql_column(app, strict_owner_session, monkeypatch):
    guard = importlib.import_module('desktop_050_guard')
    exercise_until_receipt_fixture(guard, app, monkeypatch)
