"""PostgreSQL receipt guards must compare JSON through its equality-capable type."""
from types import SimpleNamespace

from sqlalchemy import JSON, String


def test_postgresql_guard_uses_jsonb_equality_for_snapshot(monkeypatch):
    from app.database_guards import install_receipt_guards
    import sqlalchemy

    statements = []
    connection = SimpleNamespace(dialect=SimpleNamespace(name='postgresql'),
                                 exec_driver_sql=lambda sql: statements.append(sql))
    inspector = SimpleNamespace(get_table_names=lambda: ['service_print_jobs'],
        get_columns=lambda table: [
            {'name': 'id', 'type': String(36)}, {'name': 'snapshot', 'type': JSON()},
            {'name': 'status', 'type': String(20)}, {'name': 'updated_at', 'type': String(30)},
        ])
    monkeypatch.setattr(sqlalchemy, 'inspect', lambda value: inspector)
    install_receipt_guards(connection)
    trigger = next(sql for sql in statements if 'FUNCTION public.protect_receipt_service_print_jobs()' in sql)
    assert 'OLD.snapshot::jsonb IS DISTINCT FROM NEW.snapshot::jsonb' in trigger
    assert 'OLD.id IS DISTINCT FROM NEW.id' in trigger
    assert 'OLD.status IS DISTINCT FROM NEW.status' not in trigger
