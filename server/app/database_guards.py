APPEND_ONLY_TABLES = (
    'employee_identities',
    'registration_receipts',
    'registration_token_views',
    'stock_import_pending',
    'stock_import_resolutions',
    'settlement_pass_redemptions',
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
    install_member_card_guards(connection, actual_tables)
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


def install_member_card_guards(connection, actual_tables):
    """The account and original card identity survive revocation and replacement."""
    if 'member_card_bindings' not in actual_tables:
        return
    immutable = ('id', 'period_id', 'member_id', 'card_uid', 'created_by', 'terminal_id', 'created_at')
    if connection.dialect.name == 'sqlite':
        changes = ' OR '.join(f'OLD.{name} IS NOT NEW.{name}' for name in immutable)
        connection.exec_driver_sql(f'''CREATE TRIGGER IF NOT EXISTS protect_member_card_update
            BEFORE UPDATE ON member_card_bindings
            WHEN {changes} OR (OLD.is_active=0 AND NEW.is_active<>0)
            BEGIN SELECT RAISE(ABORT,'card binding identity is immutable'); END''')
        connection.exec_driver_sql('''CREATE TRIGGER IF NOT EXISTS protect_member_card_delete
            BEFORE DELETE ON member_card_bindings
            BEGIN SELECT RAISE(ABORT,'card binding is immutable'); END''')
    elif connection.dialect.name == 'postgresql':
        changes = ' OR '.join(f'OLD.{name} IS DISTINCT FROM NEW.{name}' for name in immutable)
        connection.exec_driver_sql(f'''CREATE OR REPLACE FUNCTION public.xiquan_member_card_guard()
            RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$ BEGIN
            IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'card binding is immutable'; END IF;
            IF {changes} OR (NOT OLD.is_active AND NEW.is_active) THEN
                RAISE EXCEPTION 'card binding identity is immutable'; END IF;
            RETURN NEW; END; $$''')
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS protect_member_card_update ON member_card_bindings')
        connection.exec_driver_sql('''CREATE TRIGGER protect_member_card_update
            BEFORE UPDATE OR DELETE ON member_card_bindings
            FOR EACH ROW EXECUTE FUNCTION public.xiquan_member_card_guard()''')
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS protect_member_card_truncate ON member_card_bindings')
        connection.exec_driver_sql('''CREATE TRIGGER protect_member_card_truncate
            BEFORE TRUNCATE ON member_card_bindings
            FOR EACH STATEMENT EXECUTE FUNCTION public.xiquan_member_card_guard()''')


def install_period_guards(connection):
    """No runtime bypass: old rows and cross-period references are rejected in SQL."""
    from sqlalchemy import inspect

    from .extensions import db
    from .models import PeriodMixin

    inspector = inspect(connection)
    if 'business_state' not in inspector.get_table_names():
        return  # The preceding schema revision is still allowed to install its guards.
    actual_tables = set(inspector.get_table_names())
    install_receipt_guards(connection)
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
            if operation == 'DELETE' and name in RECEIPT_TABLES:
                allowed = receipt_delete_condition(connection, name)
                condition = f'({condition}) AND NOT ({allowed})'
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
    for name in (*tables, 'catalog_items', 'wristbands',
                 *(name for name in ('stock_items', 'stock_import_pending', 'stock_import_resolutions') if name in actual_tables)):
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


RECEIPT_TABLES = ('print_jobs', 'service_print_jobs', 'settlement_print_attempts', 'service_print_attempts')


def receipt_delete_condition(connection, name):
    if connection.dialect.name == 'postgresql':
        return 'public.xiquan_receipt_delete_allowed(TG_RELID,TG_TABLE_NAME,to_jsonb(OLD))'
    created = 'OLD.created_at'
    if name in {'settlement_print_attempts','service_print_attempts'}:
        parent = 'print_jobs' if name=='settlement_print_attempts' else 'service_print_jobs'
        created = f'(SELECT created_at FROM {parent} WHERE id=OLD.job_id)'
    return f"(xiquan_receipt_cutoff()<>'' AND julianday({created})<julianday(xiquan_receipt_cutoff()))"


def install_receipt_guards(connection):
    """No GUC, SET ROLE or API request can authorize deleting receipt evidence."""
    from sqlalchemy import JSON, inspect
    from .business_barrier import BARRIER_KEY
    tables = set(inspect(connection).get_table_names())
    dialect = connection.dialect.name
    if dialect == 'postgresql':
        connection.exec_driver_sql(f'''CREATE OR REPLACE FUNCTION public.xiquan_receipt_delete_allowed(
          target oid, name text, old_row jsonb) RETURNS boolean LANGUAGE plpgsql
          SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE created timestamptz; cutoff timestamptz;
        BEGIN
          IF name NOT IN ('print_jobs','service_print_jobs','settlement_print_attempts','service_print_attempts')
            OR NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
              JOIN pg_roles r ON r.oid=c.relowner JOIN pg_database d ON d.datname=current_database()
              JOIN pg_roles login ON login.rolname=session_user
              WHERE c.oid=target AND c.relname=name AND n.nspname='public' AND r.rolname=session_user
                AND d.datdba=login.oid AND login.oid=CASE WHEN n.nspowner=(SELECT oid FROM pg_roles
                  WHERE rolname='pg_database_owner') THEN d.datdba ELSE n.nspowner END)
            OR NOT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid()
              AND classid=0 AND objid={BARRIER_KEY} AND objsubid=1 AND mode='ExclusiveLock' AND granted)
          THEN RETURN false; END IF;
          IF name='service_print_attempts' THEN
            SELECT created_at INTO created FROM public.service_print_jobs WHERE id=old_row->>'job_id';
          ELSIF name='settlement_print_attempts' THEN
            SELECT created_at INTO created FROM public.print_jobs WHERE id=old_row->>'job_id';
          ELSE created := (old_row->>'created_at')::timestamptz; END IF;
          cutoff := date_trunc('day',CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai') AT TIME ZONE 'Asia/Shanghai';
          RETURN COALESCE(created<cutoff,false);
        END; $$''')
        connection.exec_driver_sql('REVOKE ALL ON FUNCTION public.xiquan_receipt_delete_allowed(oid,text,jsonb) FROM PUBLIC')
    for name in RECEIPT_TABLES:
        if name not in tables: continue
        column_types = {column['name']: column['type'] for column in inspect(connection).get_columns(name)}
        columns = set(column_types)
        mutable = {'updated_at','status','attempts','last_error','printed_at'} if name in {'print_jobs','service_print_jobs'} else {'updated_at','success','error','finished_at'}
        immutable = sorted(columns-mutable)
        if dialect == 'sqlite':
            allowed = receipt_delete_condition(connection,name)
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS protect_receipt_{name}_delete')
            connection.exec_driver_sql(f'''CREATE TRIGGER protect_receipt_{name}_delete BEFORE DELETE ON {name}
              WHEN NOT ({allowed}) BEGIN SELECT RAISE(ABORT,'receipt cleanup requires owner and expiry'); END''')
            changes = ' OR '.join(f'OLD.{column} IS NOT NEW.{column}' for column in immutable)
            if 'finished_at' in columns:
                changes += ' OR (OLD.finished_at IS NOT NULL AND (OLD.success IS NOT NEW.success OR OLD.error IS NOT NEW.error OR OLD.finished_at IS NOT NEW.finished_at))'
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS protect_receipt_{name}_update')
            connection.exec_driver_sql(f'''CREATE TRIGGER protect_receipt_{name}_update BEFORE UPDATE ON {name}
              WHEN {changes} BEGIN SELECT RAISE(ABORT,'receipt snapshot and identity are immutable'); END''')
        elif dialect == 'postgresql':
            changes = ' OR '.join(
                f'OLD.{column}::jsonb IS DISTINCT FROM NEW.{column}::jsonb'
                if isinstance(column_types[column], JSON)
                else f'OLD.{column} IS DISTINCT FROM NEW.{column}' for column in immutable)
            if 'finished_at' in columns:
                changes += ' OR (OLD.finished_at IS NOT NULL AND ROW(OLD.success,OLD.error,OLD.finished_at) IS DISTINCT FROM ROW(NEW.success,NEW.error,NEW.finished_at))'
            connection.exec_driver_sql(f'''CREATE OR REPLACE FUNCTION public.protect_receipt_{name}()
              RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$ BEGIN
              IF TG_OP='DELETE' THEN
                IF NOT public.xiquan_receipt_delete_allowed(TG_RELID,TG_TABLE_NAME,to_jsonb(OLD))
                  THEN RAISE EXCEPTION 'receipt cleanup requires owner and expiry'; END IF;
                RETURN OLD;
              END IF;
              IF {changes} THEN RAISE EXCEPTION 'receipt snapshot and identity are immutable'; END IF;
              RETURN NEW; END; $$''')
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS protect_receipt ON {name}')
            connection.exec_driver_sql(f'CREATE TRIGGER protect_receipt BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION public.protect_receipt_{name}()')


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
