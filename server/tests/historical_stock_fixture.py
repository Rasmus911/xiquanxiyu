"""Explicit pre-0.5.5 evidence fixture, never an alternative current-order API."""
from decimal import Decimal
from app.extensions import db
from app.models import Employee, OrderItem, StockItem
from app.stock_service import consume_order

def historical_consumption(item_id, selections):
    item = db.session.get(OrderItem, item_id)
    actor = db.session.get(Employee, item.created_by_id)
    rows = [dict(stock_item_id=identifier, quantity=Decimal(quantity)) for identifier, quantity in selections]
    masters = {row['stock_item_id']: db.session.get(StockItem, row['stock_item_id']) for row in rows}
    consume_order(item, rows, masters, actor)
    db.session.commit()
