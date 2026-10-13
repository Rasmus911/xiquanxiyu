"""Pending Excel rows survive periods and cannot be edited into new evidence."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from app.extensions import db


def test_pending_source_and_resolution_are_immutable(client, admin_session):
    from app.models import StockImportPending, StockImportResolution
    actor = admin_session['login']['employee']['id']
    row = StockImportPending(name='新品', base_quantity='800', package_cost='120',
        source_sha256='a' * 64, source_row=3, created_by_id=actor)
    db.session.add(row); db.session.commit()
    assert row.id and row.base_quantity == 800
    with pytest.raises(DatabaseError):
        db.session.execute(text('UPDATE stock_import_pending SET base_quantity=1 WHERE id=:id'), {'id': row.id})
    db.session.rollback()
    resolution = StockImportResolution(pending_id=row.id, outcome='cancelled', created_by_id=actor)
    db.session.add(resolution); db.session.commit()
    with pytest.raises(DatabaseError):
        db.session.execute(text('DELETE FROM stock_import_resolutions WHERE id=:id'), {'id': resolution.id})
    db.session.rollback()
