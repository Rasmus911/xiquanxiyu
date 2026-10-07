from types import SimpleNamespace

from app.database_guards import install_database_guards


def test_postgres_guards_do_not_resolve_caller_temporary_tables(monkeypatch):
    from app.database_guards import APPEND_ONLY_TABLES
    monkeypatch.setattr('sqlalchemy.inspect',lambda connection: SimpleNamespace(get_table_names=lambda: [*APPEND_ONLY_TABLES, 'settlements']))
    statements = []
    connection = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), exec_driver_sql=statements.append)
    install_database_guards(connection)
    functions = [sql for sql in statements if "CREATE OR REPLACE FUNCTION" in sql]
    assert len(functions) == 4
    assert all("SET search_path = pg_catalog, public, pg_temp" in sql for sql in functions)
    settled_guard = next(sql for sql in functions if "xiquan_settled_order_guard" in sql)
    assert settled_guard.count("FROM public.settlement_visits") == 2
