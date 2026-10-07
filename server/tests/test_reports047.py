"""Marketing report counts people, not merged bills, and separates cost from cash."""
from datetime import datetime, timezone
from decimal import Decimal

from app.extensions import db
from app.models import Settlement, SettlementVisit, Visit, Wristband, Employee, Terminal


def test_insights_counts_two_visits_in_one_bill_and_local_arrival_hours(client, admin_session):
    employee = Employee.query.filter_by(username='admin').one()
    terminal = Terminal.query.filter_by(code='TEST-01').one()
    bands = Wristband.query.limit(2).all()
    visits = [Visit(wristband_id=band.id, opened_by_id=employee.id, status='closed',
                    opened_at=datetime(2026, 10, 7, 2 + i, tzinfo=timezone.utc)) for i, band in enumerate(bands)]
    db.session.add_all(visits); db.session.flush()
    bill = Settlement(number='REPORT047', total_amount=160, paid_amount=160, created_by_id=employee.id,
        terminal_id=terminal.id, idempotency_key='report-047', completed_at=datetime(2026, 10, 7, 6, tzinfo=timezone.utc))
    db.session.add(bill); db.session.flush()
    for visit in visits:
        db.session.add(SettlementVisit(settlement_id=bill.id, visit_id=visit.id, amount=80))
    db.session.commit()
    r = client.get('/api/reports/insights?start=2026-10-06T16:00:00Z&end=2026-10-07T16:00:00Z', headers=admin_session['headers'])
    assert r.status_code == 200, r.get_json()
    data = r.get_json()['data']
    assert data['current']['settlement_count'] == 1
    assert data['visit_count'] == 2
    assert data['average_visit_revenue'] == '80.00'
    assert data['hours'][10]['visits'] == 1
    assert data['hours'][11]['visits'] == 1
    assert data['previous']['operating_revenue'] == '0.00'
    assert data['member_visit_count'] == 0


def test_insights_empty_has_no_invented_average_or_profit(client, admin_session):
    r = client.get('/api/reports/insights?start=2026-01-01T00:00:00Z&end=2026-01-02T00:00:00Z', headers=admin_session['headers'])
    assert r.status_code == 200
    data = r.get_json()['data']
    assert data['average_visit_revenue'] is None
    assert data['purchase_cost']['recorded_amount'] == '0.00'
    assert data['purchase_cost']['unpriced_receipts'] == 0
    assert 'profit' not in data


def test_receiving_cost_report_uses_latest_correction_not_both_revisions(client, admin_session):
    from test_inventory047 import create, post
    h = admin_session['headers']; item = create(client, h)
    r = post(client, h, '/api/inventory/stock-adjust', {'stock_item_id':item['id'],'version':item['version'],
        'movement_type':'purchase','quantity':'4','input_unit':'package','reason':'采购入库','unit_cost':'120'}, 'report-buy')
    assert r.status_code == 200
    movement = r.get_json()['data']['movement']
    assert post(client,h,'/api/inventory/stock-movements/'+movement['id']+'/cost',
        {'unit_cost':'100','expected_cost_id':movement['cost']['id'],'password':'admin123'},'report-cost-edit').status_code == 200
    r = client.get('/api/reports/insights',headers=h)
    assert r.status_code == 200
    assert r.get_json()['data']['purchase_cost']['recorded_amount'] == '400.00'
