"""Additive cost schema keeps historical receipts and quantities intact."""
from decimal import Decimal
from app.extensions import db
from app.models import StockItem, StockMovement, StockCost


def test_migration_initializes_alert_from_last_receipt_not_current_balance(client, admin_session):
    from test_inventory047 import create, post
    from app.schema_maintenance import upgrade_insights047_schema
    h = admin_session['headers']; item = create(client, h)
    post(client, h, '/api/inventory/stock-adjust', {'stock_item_id':item['id'],'version':item['version'],
        'movement_type':'loss','quantity':'100','input_unit':'base','reason':'测试损耗'}, 'loss-migrate')
    db.session.commit()
    before_updated = db.session.get(StockItem,item['id']).updated_at
    with db.engine.begin() as connection:
        StockCost.__table__.drop(connection)
        connection.exec_driver_sql("DROP TABLE IF EXISTS schema_upgrade_markers")
        connection.exec_driver_sql("UPDATE stock_items SET low_stock_threshold=1 WHERE id='" + item['id'] + "'")
        upgrade_insights047_schema(connection)
    db.session.expire_all()
    assert db.session.get(StockItem,item['id']).stock_quantity == Decimal('700')
    assert db.session.get(StockItem,item['id']).updated_at == before_updated
    assert db.session.get(StockItem,item['id']).low_stock_threshold == Decimal('120')
    assert StockMovement.query.filter_by(stock_item_id=item['id']).count() == 2
    with db.engine.begin() as connection:
        upgrade_insights047_schema(connection)
    db.session.expire_all()
    assert db.session.get(StockItem,item['id']).stock_quantity == Decimal('700')


def test_repeated_schema_check_never_rebases_unreceipted_legacy_stock(app):
    from app.schema_maintenance import upgrade_insights047_schema
    master = StockItem(name='旧期初',base_unit='袋',stock_quantity=100,low_stock_threshold=15)
    db.session.add(master);db.session.commit();id_=master.id
    with db.engine.begin() as connection:
        upgrade_insights047_schema(connection)
        connection.exec_driver_sql("UPDATE stock_items SET stock_quantity=60 WHERE id='" + id_ + "'")
        upgrade_insights047_schema(connection)
    db.session.expire_all()
    assert db.session.get(StockItem,id_).stock_quantity == Decimal('60')
    assert db.session.get(StockItem,id_).low_stock_threshold == Decimal('15')


def test_create_all_does_not_preempt_one_time_legacy_receipt_backfill(client, admin_session):
    from app.schema_maintenance import upgrade_insights047_schema
    from app.models import CatalogItem, InventoryMovement
    product = CatalogItem(name='旧商品',kind='product',price=1,stock_tracked=True,stock_quantity=20)
    db.session.add(product);db.session.flush()
    stock = StockItem(name='旧商品',base_unit='袋',stock_quantity=20,low_stock_threshold=1,legacy_catalog_item_id=product.id)
    db.session.add(stock);db.session.flush()
    db.session.add(InventoryMovement(catalog_item_id=product.id,movement_type='purchase',quantity=100,
        balance_after=100,note='旧采购',operator_id=admin_session['login']['employee']['id']))
    db.session.commit(); id_=stock.id
    with db.engine.begin() as connection:
        connection.exec_driver_sql('DROP TABLE IF EXISTS schema_upgrade_markers')
    db.create_all()
    with db.engine.begin() as connection:
        upgrade_insights047_schema(connection)
    db.session.expire_all()
    assert db.session.get(StockItem,id_).low_stock_threshold == Decimal('15')
