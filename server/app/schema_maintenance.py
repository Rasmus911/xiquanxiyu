from sqlalchemy import inspect, text

from .extensions import db


def upgrade_operations_schema(connection):
    """Structure only: no retirement, new catalog, stock adjustment or bill repricing."""
    def add(table, name, declaration):
        if name in {column['name'] for column in inspect(connection).get_columns(table)}:
            return False
        connection.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
        return True
    added_area = add('wristbands', 'bath_area', "VARCHAR(20) NOT NULL DEFAULT 'other'")
    add('wristbands', 'is_active', 'BOOLEAN NOT NULL DEFAULT TRUE')
    if added_area:
        # A derived new column must not increment the old business revision.
        suffix = ' ON wristbands' if connection.dialect.name == 'postgresql' else ''
        connection.exec_driver_sql('DROP TRIGGER IF EXISTS revision_wristbands_update' + suffix)
        from .serializers import wristband_area
        for id_, number in connection.execute(text('SELECT id,number FROM wristbands')).all():
            connection.execute(text('UPDATE wristbands SET bath_area=:area WHERE id=:id'),
                {'area': wristband_area(number), 'id': id_})
    add('catalog_items','reference_code','VARCHAR(80)')
    add('catalog_items','package_definition','JSON')
    connection.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_catalog_reference_code ON catalog_items (reference_code)')
    add('order_items','covered_quantity','NUMERIC(12,3) NOT NULL DEFAULT 0 CHECK (covered_quantity >= 0 AND covered_quantity <= quantity)')
    add('order_items','package_order_item_id','VARCHAR(36) REFERENCES order_items(id)')
    add('order_items','package_snapshot','JSON')
    from .database_guards import install_database_guards, install_period_guards
    from .business_barrier import install_barrier_guards
    install_database_guards(connection)
    install_period_guards(connection)
    install_barrier_guards(connection)


def upgrade_business_period_schema(connection):
    """Add attribution without touching an existing business value or removing evidence guards."""
    from .business_period import INITIAL_PERIOD_ID
    from .database_guards import install_database_guards, install_period_guards
    from .models import (
        AccessPolicyModel,
        BusinessPeriod,
        BusinessStateModel,
        PeriodMixin,
        ResetEventModel,
        ResetTaskModel,
        utcnow,
    )

    # sqlite3's legacy transaction mode otherwise auto-commits DDL statements.
    if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql('BEGIN')
    for model in (BusinessPeriod, BusinessStateModel, AccessPolicyModel, ResetTaskModel, ResetEventModel):
        model.__table__.create(connection, checkfirst=True)
    if 'administrator_employee_ids' not in {
            column['name'] for column in inspect(connection).get_columns('access_policies')}:
        connection.exec_driver_sql("ALTER TABLE access_policies ADD COLUMN "
                                   "administrator_employee_ids JSON NOT NULL DEFAULT '[]'")
    if connection.execute(text('SELECT id FROM business_periods WHERE id=:id'),
                          {'id': INITIAL_PERIOD_ID}).first() is None:
        connection.execute(BusinessPeriod.__table__.insert().values(id=INITIAL_PERIOD_ID, created_at=utcnow()))
    models = [mapper.class_ for mapper in db.Model.registry.mappers if issubclass(mapper.class_, PeriodMixin)]
    for model in models:
        name = model.__tablename__
        if name not in inspect(connection).get_table_names():
            continue  # Future tables are created by their own structural revision.
        if 'period_id' not in {column['name'] for column in inspect(connection).get_columns(name)}:
            connection.exec_driver_sql(f"ALTER TABLE {name} ADD COLUMN period_id VARCHAR(36) "
                                       f"NOT NULL DEFAULT '{INITIAL_PERIOD_ID}' REFERENCES business_periods(id)")
        connection.exec_driver_sql(f'CREATE INDEX IF NOT EXISTS ix_{name}_period_id ON {name} (period_id)')
    member_indexes = inspect(connection).get_indexes('members')
    if any(index['name'] == 'ix_members_phone' and index['unique'] for index in member_indexes):
        connection.exec_driver_sql('DROP INDEX ix_members_phone')
        connection.exec_driver_sql('CREATE INDEX ix_members_phone ON members (phone)')
    connection.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_members_period_phone '
                               'ON members (period_id, phone)')
    indexes = inspect(connection).get_indexes('visits')
    if any(index['name'] == 'uq_visits_active_wristband' and index['column_names'] == ['wristband_id']
           for index in indexes):
        connection.exec_driver_sql('DROP INDEX uq_visits_active_wristband')
    connection.exec_driver_sql('CREATE UNIQUE INDEX IF NOT EXISTS uq_visits_active_wristband '
                               "ON visits (period_id, wristband_id) WHERE status IN ('open', 'settling')")
    if connection.execute(text('SELECT id FROM business_state WHERE id=1')).first() is None:
        connection.execute(BusinessStateModel.__table__.insert().values(id=1, period_id=INITIAL_PERIOD_ID))
    install_database_guards(connection)
    install_period_guards(connection)
    # Portable SQLite upgrades share the same structural maintenance ownership
    # addition as Alembic. This never schedules/replays a reset or touches money.
    if 'maintenance_reset_id' not in {column['name'] for column in inspect(connection).get_columns('business_state')}:
        connection.exec_driver_sql('ALTER TABLE business_state ADD COLUMN maintenance_reset_id VARCHAR(36)')
    from .business_barrier import install_barrier_guards
    install_barrier_guards(connection)


def ensure_runtime_schema():
    """为直接运行 EXE 的现有 SQLite/PostgreSQL 数据库补充兼容字段。"""
    inspector = inspect(db.engine)
    if "visits" not in inspector.get_table_names():
        return
    audit_columns = {column["name"] for column in inspector.get_columns("audit_logs")}
    if "integrity_version" not in audit_columns:
        db.session.execute(text("ALTER TABLE audit_logs ADD COLUMN integrity_version INTEGER NOT NULL DEFAULT 1"))
    if "context" not in audit_columns:
        db.session.execute(text("ALTER TABLE audit_logs ADD COLUMN context JSON NOT NULL DEFAULT '{}'"))
    db.session.commit()
    from .database_guards import install_database_guards

    install_database_guards(db.session.connection())
    db.session.commit()
    columns = {column["name"] for column in inspector.get_columns("visits")}
    if "party_id" not in columns:
        db.session.connection().execute(text("ALTER TABLE visits ADD COLUMN party_id VARCHAR(36)"))
        db.session.commit()
    db.session.connection().execute(text("CREATE INDEX IF NOT EXISTS ix_visits_party_id ON visits (party_id)"))
    db.session.commit()

    inspector = inspect(db.engine)
    if "employees" in inspector.get_table_names():
        employee_columns = {column["name"] for column in inspector.get_columns("employees")}
        if "session_version" not in employee_columns:
            db.session.execute(text("ALTER TABLE employees ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1"))
            db.session.commit()
        if "allowed_channels" not in employee_columns:
            db.session.execute(text("ALTER TABLE employees ADD COLUMN allowed_channels JSON NOT NULL DEFAULT '[]'"))
            db.session.commit()
        if "deleted_at" not in employee_columns:
            timestamp_type = 'TIMESTAMP WITH TIME ZONE' if db.engine.dialect.name == 'postgresql' else 'DATETIME'
            db.session.execute(text(f'ALTER TABLE employees ADD COLUMN deleted_at {timestamp_type}'))
            db.session.commit()
        if "mobile_full_access" not in employee_columns:
            db.session.execute(
                text("ALTER TABLE employees ADD COLUMN mobile_full_access BOOLEAN NOT NULL DEFAULT FALSE")
            )
            db.session.commit()

    inspector = inspect(db.engine)
    if "catalog_items" not in inspector.get_table_names():
        return
    catalog_columns = {column["name"] for column in inspector.get_columns("catalog_items")}
    if "mobile_scope" not in catalog_columns:
        db.session.execute(
            text("ALTER TABLE catalog_items ADD COLUMN mobile_scope VARCHAR(20) NOT NULL DEFAULT 'frontdesk'")
        )
        db.session.execute(
            text(
                "UPDATE catalog_items SET mobile_scope = 'scrub' WHERE category IN ('搓澡助浴', '组合项目', '洗浴用品')"
            )
        )
        db.session.execute(
            text(
                "UPDATE catalog_items SET mobile_scope = 'rest' "
                "WHERE category IN ('理疗按摩', '饮品', '承德特色饮品', '食品')"
            )
        )
        db.session.commit()

    db.session.commit()
    with db.engine.begin() as connection:
        upgrade_business_period_schema(connection)
        upgrade_operations_schema(connection)
        upgrade_independent_stock_schema(connection)
        upgrade_desktop_ops_schema(connection)
        upgrade_insights047_schema(connection)
        upgrade_ordering048_schema(connection)
    db.session.expire_all()


def upgrade_independent_stock_schema(connection):
    """Preserve historical rows; map each tracked product to a base-unit master."""
    from sqlalchemy import select
    from .models import StockItem, StockMovement, OrderStockConsumption, CatalogItem
    if 'inventory_mode' not in {column['name'] for column in inspect(connection).get_columns('order_items')}:
        connection.exec_driver_sql("ALTER TABLE order_items ADD COLUMN inventory_mode VARCHAR(20) NOT NULL DEFAULT 'legacy'")
    for model in (StockItem, StockMovement, OrderStockConsumption):
        model.__table__.create(connection, checkfirst=True)
    mapped = set(connection.execute(select(StockItem.__table__.c.legacy_catalog_item_id)).scalars())
    # This earlier migration also runs before later additive model fields exist.
    products = connection.execute(select(*(CatalogItem.__table__.c[name] for name in
        ('id', 'name', 'category', 'stock_quantity', 'low_stock_threshold', 'is_active'))).where(
        CatalogItem.stock_tracked.is_(True), CatalogItem.kind=='product')).mappings()
    for item in products:
        if item['id'] not in mapped:
            connection.execute(StockItem.__table__.insert().values(name=item['name'], category=item['category'],
                base_unit='原销售单位', package_unit='', units_per_package=1, package_spec='',
                stock_quantity=item['stock_quantity'], low_stock_threshold=item['low_stock_threshold'],
                is_active=item['is_active'], legacy_catalog_item_id=item['id']))
    from .database_guards import install_database_guards, install_period_guards
    from .business_barrier import install_barrier_guards
    install_database_guards(connection); install_period_guards(connection); install_barrier_guards(connection)
    if connection.dialect.name == 'postgresql':
        # Existing dedicated roles must receive new-table grants after upgrade;
        # this neither enables login nor gives ownership/control-table authority.
        connection.exec_driver_sql('''DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_app') THEN
            GRANT SELECT,INSERT,UPDATE,DELETE ON stock_items TO xiquan_app;
            GRANT SELECT,INSERT ON stock_movements,order_stock_consumptions TO xiquan_app;
            REVOKE UPDATE,DELETE,TRUNCATE ON stock_movements,order_stock_consumptions FROM xiquan_app;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_reset') THEN
            GRANT SELECT ON stock_items,stock_movements,order_stock_consumptions TO xiquan_reset;
            GRANT UPDATE(stock_quantity,version,updated_at) ON stock_items TO xiquan_reset;
            GRANT INSERT ON stock_movements TO xiquan_reset;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_backup') THEN
            GRANT SELECT ON stock_items,stock_movements,order_stock_consumptions TO xiquan_backup;
          END IF;
        END $$''')


def upgrade_desktop_ops_schema(connection):
    """Only add nullable tombstones; retain every existing row and binding."""
    timestamp_type = 'TIMESTAMP WITH TIME ZONE' if connection.dialect.name == 'postgresql' else 'DATETIME'
    for table in ('members', 'catalog_items'):
        columns = {column['name'] for column in inspect(connection).get_columns(table)}
        if 'deleted_at' not in columns:
            connection.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN deleted_at {timestamp_type}')


def upgrade_insights047_schema(connection):
    """Add cost evidence only; initialize alerts without rewriting stock history."""
    from sqlalchemy import select, update
    from .models import StockItem, StockMovement, StockCost, CatalogItem, InventoryMovement
    from .stock_cost_service import warning_quantity
    # Not an ORM table: create_all must not preempt this durable one-time backfill.
    connection.exec_driver_sql('CREATE TABLE IF NOT EXISTS schema_upgrade_markers (revision VARCHAR(80) PRIMARY KEY)')
    initialize_alerts = connection.execute(text("SELECT revision FROM schema_upgrade_markers WHERE revision='20261007_insights_cost'")).first() is None
    StockCost.__table__.create(connection, checkfirst=True)
    stock = StockItem.__table__; movements = StockMovement.__table__
    # This preceding revision can run before the later nullable master cost
    # column exists. Select only its original fields, not the future ORM table.
    fields = ('id','legacy_catalog_item_id','stock_quantity')
    for row in connection.execute(select(*(stock.c[name] for name in fields))).mappings() if initialize_alerts else ():
        received = connection.execute(select(movements.c.quantity).where(
            movements.c.stock_item_id==row['id'], movements.c.movement_type.in_(('purchase','opening')),
            movements.c.quantity>0).order_by(movements.c.created_at.desc(), movements.c.id.desc()).limit(1)).scalar_one_or_none()
        if received is None and row['legacy_catalog_item_id']:
            legacy = InventoryMovement.__table__
            received = connection.execute(select(legacy.c.quantity).where(
                legacy.c.catalog_item_id==row['legacy_catalog_item_id'],legacy.c.quantity>0,
                legacy.c.movement_type.in_(('purchase','opening'))).order_by(
                legacy.c.created_at.desc(),legacy.c.id.desc()).limit(1)).scalar_one_or_none()
        threshold = warning_quantity(received if received is not None else row['stock_quantity'])
        connection.execute(update(stock).where(stock.c.id==row['id']).values(
            low_stock_threshold=threshold,updated_at=stock.c.updated_at))
        if row['legacy_catalog_item_id']:
            connection.execute(update(CatalogItem.__table__).where(CatalogItem.id==row['legacy_catalog_item_id']).values(
                low_stock_threshold=threshold,updated_at=CatalogItem.__table__.c.updated_at))
    if initialize_alerts:
        connection.execute(text("INSERT INTO schema_upgrade_markers(revision) VALUES ('20261007_insights_cost')"))
    from .database_guards import install_database_guards
    from .business_barrier import install_barrier_guards
    install_database_guards(connection); install_barrier_guards(connection)
    if connection.dialect.name == 'postgresql':
        connection.exec_driver_sql('''DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_app') THEN
            GRANT SELECT,INSERT ON stock_costs TO xiquan_app;
            GRANT SELECT ON schema_upgrade_markers TO xiquan_app;
            REVOKE UPDATE,DELETE,TRUNCATE ON stock_costs FROM xiquan_app;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_reset') THEN
            GRANT SELECT ON stock_costs,schema_upgrade_markers TO xiquan_reset;
          END IF;
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='xiquan_backup') THEN
            GRANT SELECT ON stock_costs,schema_upgrade_markers TO xiquan_backup;
          END IF;
        END $$''')


def upgrade_ordering048_schema(connection):
    """Keep financial snapshots/quantities; add an optional base-unit cost only."""
    from sqlalchemy import update, or_
    from .models import CatalogItem
    if 'unit_cost' not in {column['name'] for column in inspect(connection).get_columns('stock_items')}:
        connection.exec_driver_sql('ALTER TABLE stock_items ADD COLUMN unit_cost NUMERIC(12,2)')
    table = CatalogItem.__table__
    connection.execute(update(table).where(table.c.kind=='product',or_(
        table.c.name.in_(('澡巾','备品','搓泥宝')),
        table.c.reference_code.in_(('bath.towel','bath.supplies','bath.mud'))
    )).values(kind='service',stock_tracked=False,updated_at=table.c.updated_at))
