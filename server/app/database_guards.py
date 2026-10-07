APPEND_ONLY_TABLES = (
    "audit_logs",
    "payments",
    "stored_value_ledgers",
    "pass_ledgers",
    "inventory_movements",
    "settlement_visits",
    "revoked_sessions",
    "idempotency_records",
    "stock_movements",
    "stock_costs",
    "order_stock_consumptions",
)


def install_database_guards(connection):
    from sqlalchemy import inspect
    actual_tables = set(inspect(connection).get_table_names())
    append_tables = tuple(name for name in APPEND_ONLY_TABLES if name in actual_tables)
    dialect = connection.dialect.name
    if dialect == "sqlite":
        for table in append_tables:
            for operation in ("UPDATE", "DELETE"):
                connection.exec_driver_sql(f"""
                    CREATE TRIGGER IF NOT EXISTS protect_{table}_{operation.lower()}
                    BEFORE {operation} ON {table}
                    BEGIN SELECT RAISE(ABORT, 'immutable financial or audit record'); END
                """)
        for operation in ("UPDATE", "DELETE"):
            new_visit_guard = (
                "OR EXISTS (SELECT 1 FROM settlement_visits WHERE visit_id = NEW.visit_id)"
                if operation == "UPDATE"
                else ""
            )
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS protect_settled_order_{operation.lower()}")
            connection.exec_driver_sql(f"""
                CREATE TRIGGER IF NOT EXISTS protect_settled_order_{operation.lower()}
                BEFORE {operation} ON order_items
                WHEN EXISTS (SELECT 1 FROM settlement_visits WHERE visit_id = OLD.visit_id)
                  {new_visit_guard}
                BEGIN SELECT RAISE(ABORT, 'settled order is immutable'); END
            """)
        connection.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS protect_settled_order_insert
            BEFORE INSERT ON order_items
            WHEN EXISTS (SELECT 1 FROM settlement_visits WHERE visit_id = NEW.visit_id)
            BEGIN SELECT RAISE(ABORT, 'settled order is immutable'); END
        """)
        connection.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS protect_settlement_update BEFORE UPDATE ON settlements
            WHEN OLD.id IS NOT NEW.id OR OLD.created_at IS NOT NEW.created_at
              OR OLD.shift_id IS NOT NEW.shift_id OR OLD.number IS NOT NEW.number
              OR OLD.total_amount IS NOT NEW.total_amount
              OR OLD.paid_amount IS NOT NEW.paid_amount OR OLD.created_by_id IS NOT NEW.created_by_id
              OR OLD.terminal_id IS NOT NEW.terminal_id OR OLD.member_id IS NOT NEW.member_id
              OR OLD.idempotency_key IS NOT NEW.idempotency_key OR OLD.completed_at IS NOT NEW.completed_at
              OR NOT (NEW.status = OLD.status OR (OLD.status = 'completed' AND NEW.status = 'refunded'))
            BEGIN SELECT RAISE(ABORT, 'settlement financial fields are immutable'); END
        """)
        connection.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS protect_settlement_delete BEFORE DELETE ON settlements
            BEGIN SELECT RAISE(ABORT, 'settlement is immutable'); END
        """)
    elif dialect == "postgresql":
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION public.xiquan_append_only() RETURNS trigger LANGUAGE plpgsql
            SET search_path = pg_catalog, public, pg_temp AS $$
            BEGIN RAISE EXCEPTION 'immutable financial or audit record'; END; $$
        """)
        for table in (*append_tables, "settlements"):
            operations = "DELETE OR TRUNCATE" if table == "settlements" else "UPDATE OR DELETE OR TRUNCATE"
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS xiquan_immutable ON {table}")
            connection.exec_driver_sql(f"""
                CREATE TRIGGER xiquan_immutable BEFORE {operations} ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION public.xiquan_append_only()
            """)
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION public.xiquan_settled_order_guard() RETURNS trigger LANGUAGE plpgsql
            SET search_path = pg_catalog, public, pg_temp AS $$
            BEGIN
                IF TG_OP <> 'INSERT' AND EXISTS (
                    SELECT 1 FROM public.settlement_visits WHERE visit_id = OLD.visit_id
                ) THEN
                    RAISE EXCEPTION 'settled order is immutable';
                END IF;
                IF TG_OP <> 'DELETE' AND EXISTS (
                    SELECT 1 FROM public.settlement_visits WHERE visit_id = NEW.visit_id
                ) THEN
                    RAISE EXCEPTION 'settled order is immutable';
                END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END; $$
        """)
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS xiquan_settled_order ON order_items")
        connection.exec_driver_sql("""
            CREATE TRIGGER xiquan_settled_order BEFORE INSERT OR UPDATE OR DELETE ON order_items
            FOR EACH ROW EXECUTE FUNCTION public.xiquan_settled_order_guard()
        """)
        connection.exec_driver_sql("""
            CREATE OR REPLACE FUNCTION public.xiquan_settlement_guard() RETURNS trigger LANGUAGE plpgsql
            SET search_path = pg_catalog, public, pg_temp AS $$
            BEGIN
                IF ROW(OLD.id, OLD.created_at, OLD.shift_id, OLD.number, OLD.total_amount,
                       OLD.paid_amount, OLD.created_by_id, OLD.terminal_id,
                       OLD.member_id, OLD.idempotency_key, OLD.completed_at)
                   IS DISTINCT FROM
                   ROW(NEW.id, NEW.created_at, NEW.shift_id, NEW.number, NEW.total_amount,
                       NEW.paid_amount, NEW.created_by_id, NEW.terminal_id,
                       NEW.member_id, NEW.idempotency_key, NEW.completed_at)
                   OR NOT (NEW.status = OLD.status OR (OLD.status = 'completed' AND NEW.status = 'refunded')) THEN
                    RAISE EXCEPTION 'settlement financial fields are immutable';
                END IF;
                RETURN NEW;
            END; $$
        """)
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS xiquan_settlement_update ON settlements")
        connection.exec_driver_sql("""
            CREATE TRIGGER xiquan_settlement_update BEFORE UPDATE ON settlements
            FOR EACH ROW EXECUTE FUNCTION public.xiquan_settlement_guard()
        """)
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS xiquan_no_truncate ON order_items")
        connection.exec_driver_sql("""
            CREATE TRIGGER xiquan_no_truncate BEFORE TRUNCATE ON order_items
            FOR EACH STATEMENT EXECUTE FUNCTION public.xiquan_append_only()
        """)
    if 'order_stock_consumptions' in actual_tables:
        if dialect == 'sqlite':
            connection.exec_driver_sql('''CREATE TRIGGER IF NOT EXISTS protect_stock_consumption_insert
                BEFORE INSERT ON order_stock_consumptions
                WHEN EXISTS (SELECT 1 FROM order_items o WHERE o.id=NEW.order_item_id AND
                    (o.status != 'active' OR EXISTS (SELECT 1 FROM settlement_visits s WHERE s.visit_id=o.visit_id)))
                BEGIN SELECT RAISE(ABORT,'closed order consumption is immutable'); END''')
        elif dialect == 'postgresql':
            connection.exec_driver_sql('''CREATE OR REPLACE FUNCTION public.xiquan_stock_consumption_guard()
                RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$ BEGIN
                IF EXISTS (SELECT 1 FROM public.order_items o WHERE o.id=NEW.order_item_id AND
                  (o.status != 'active' OR EXISTS (SELECT 1 FROM public.settlement_visits s WHERE s.visit_id=o.visit_id)))
                THEN RAISE EXCEPTION 'closed order consumption is immutable'; END IF;
                RETURN NEW; END; $$''')
            connection.exec_driver_sql('DROP TRIGGER IF EXISTS protect_stock_consumption_insert ON order_stock_consumptions')
            connection.exec_driver_sql('''CREATE TRIGGER protect_stock_consumption_insert BEFORE INSERT ON order_stock_consumptions
                FOR EACH ROW EXECUTE FUNCTION public.xiquan_stock_consumption_guard()''')


def install_period_guards(connection):
    """No runtime bypass: old rows and cross-period references are rejected in SQL."""
    from sqlalchemy import inspect

    from .extensions import db
    from .models import PeriodMixin

    inspector = inspect(connection)
    if 'business_state' not in inspector.get_table_names():
        return  # The preceding schema revision is still allowed to install its guards.
    actual_tables = set(inspector.get_table_names())
    tables = {mapper.local_table.name: mapper.local_table for mapper in db.Model.registry.mappers
              if issubclass(mapper.class_, PeriodMixin) and mapper.local_table.name in actual_tables}
    for name, table in tables.items():
        actual_columns = {c['name'] for c in inspector.get_columns(name)}
        if 'period_id' not in actual_columns:
            continue
        refs = [(fk.parent.name, fk.column.table.name, fk.column.name)
                for fk in table.foreign_keys if fk.column.table.name in tables and fk.parent.name in actual_columns]
        for operation in ('INSERT', 'UPDATE', 'DELETE'):
            conditions = []
            if operation != 'INSERT':
                conditions.append('OLD.period_id IS DISTINCT FROM (SELECT period_id FROM business_state WHERE id=1)')
            if operation != 'DELETE':
                conditions.append('NEW.period_id IS DISTINCT FROM (SELECT period_id FROM business_state WHERE id=1)')
                conditions.append('NEW.period_id IS NULL')
                for column, parent, pk in refs:
                    conditions.append(f'(NEW.{column} IS NOT NULL AND NOT EXISTS '
                                      f'(SELECT 1 FROM {parent} WHERE {pk}=NEW.{column} '
                                      'AND period_id=NEW.period_id))')
                if name == 'order_items' and 'package_order_item_id' in actual_columns:
                    conditions.append('(NEW.covered_quantity < 0 OR NEW.covered_quantity > NEW.quantity)')
                    conditions.append('(NEW.covered_quantity > 0 AND (NEW.package_order_item_id IS NULL OR NOT EXISTS '
                        '(SELECT 1 FROM order_items p WHERE p.id=NEW.package_order_item_id '
                        "AND p.period_id=NEW.period_id AND p.visit_id=NEW.visit_id AND p.kind='package' AND p.status='active')))" )
                    conditions.append('(NEW.covered_quantity=0 AND NEW.package_order_item_id IS NOT NULL)')
            if operation == 'UPDATE':
                conditions.append('OLD.period_id IS DISTINCT FROM NEW.period_id')
            condition = ' OR '.join(conditions)
            trigger = f'period_{name}_{operation.lower()}'
            if connection.dialect.name == 'sqlite':
                condition = condition.replace('IS DISTINCT FROM', 'IS NOT')
                connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS {trigger}')
                connection.exec_driver_sql(f'CREATE TRIGGER IF NOT EXISTS {trigger} '
                                          f'BEFORE {operation} ON {name} WHEN {condition} '
                                          "BEGIN SELECT RAISE(ABORT, 'business period violation'); END")
            elif connection.dialect.name == 'postgresql':
                connection.exec_driver_sql(f"""
                    CREATE OR REPLACE FUNCTION public.{trigger}() RETURNS trigger LANGUAGE plpgsql
                    SET search_path = pg_catalog, public, pg_temp AS $$ BEGIN
                    IF {condition} THEN RAISE EXCEPTION 'business period violation'; END IF;
                    RETURN {'OLD' if operation == 'DELETE' else 'NEW'}; END; $$
                """)
                connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS {trigger} ON {name}')
                connection.exec_driver_sql(f'CREATE TRIGGER {trigger} BEFORE {operation} ON {name} '
                                          f'FOR EACH ROW EXECUTE FUNCTION public.{trigger}()')
        if connection.dialect.name == 'postgresql':
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS period_no_truncate ON {name}')
            connection.exec_driver_sql(f'CREATE TRIGGER period_no_truncate BEFORE TRUNCATE ON {name} '
                                      'FOR EACH STATEMENT EXECUTE FUNCTION public.xiquan_append_only()')
    # SQL-level increments also cover trusted Core writes, and roll back with the data.
    for name in (*tables, 'catalog_items', 'wristbands', *(['stock_items'] if 'stock_items' in actual_tables else [])):
        for operation in ('INSERT', 'UPDATE', 'DELETE'):
            trigger = f'revision_{name}_{operation.lower()}'
            if connection.dialect.name == 'sqlite':
                connection.exec_driver_sql(f'CREATE TRIGGER IF NOT EXISTS {trigger} AFTER {operation} ON {name} '
                                          'BEGIN UPDATE business_state SET business_revision=business_revision+1 '
                                          'WHERE id=1; END')
            elif connection.dialect.name == 'postgresql':
                connection.exec_driver_sql("""
                    CREATE OR REPLACE FUNCTION public.xiquan_business_revision() RETURNS trigger LANGUAGE plpgsql
                    SECURITY DEFINER
                    SET search_path = pg_catalog, public, pg_temp AS $$ BEGIN
                    UPDATE public.business_state SET business_revision=business_revision+1 WHERE id=1;
                    RETURN NULL; END; $$
                """)
                connection.exec_driver_sql('REVOKE ALL ON FUNCTION public.xiquan_business_revision() FROM PUBLIC')
                connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS {trigger} ON {name}')
                connection.exec_driver_sql(f'CREATE TRIGGER {trigger} AFTER {operation} ON {name} '
                                          'FOR EACH ROW EXECUTE FUNCTION public.xiquan_business_revision()')


def remove_database_guards(connection):
    from sqlalchemy import inspect
    actual_tables = set(inspect(connection).get_table_names())
    append_tables = tuple(name for name in APPEND_ONLY_TABLES if name in actual_tables)
    if connection.dialect.name == "sqlite":
        for table in append_tables:
            for operation in ("update", "delete"):
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS protect_{table}_{operation}")
        for operation in ("insert", "update", "delete"):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS protect_settled_order_{operation}")
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS protect_settlement_{operation}")
    elif connection.dialect.name == "postgresql":
        for table in (*append_tables, "settlements"):
            connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS xiquan_immutable ON {table}")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS xiquan_settled_order ON order_items")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS xiquan_settlement_update ON settlements")
        connection.exec_driver_sql("DROP TRIGGER IF EXISTS xiquan_no_truncate ON order_items")
