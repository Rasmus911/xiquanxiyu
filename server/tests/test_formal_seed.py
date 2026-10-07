from app.extensions import db
from app.models import CatalogItem, Wristband
from app.seed import seed_defaults


def test_seed_does_not_restore_old_catalog_or_wristbands_into_existing_database(app):
    product = CatalogItem.query.filter_by(name='矿泉水').one()
    product.stock_quantity = 5
    missing_band = Wristband.query.filter_by(number='8002').one()
    db.session.delete(missing_band)
    service = CatalogItem.query.filter_by(kind='service').first()
    db.session.delete(service)
    db.session.commit()
    count = CatalogItem.query.count()
    seed_defaults()
    assert Wristband.query.filter_by(number='8002').count() == 0
    assert CatalogItem.query.count() == count
    assert product.stock_quantity == 5


def test_empty_database_seeds_formal_price_list_and_hundred_new_numbers(tmp_path):
    from app import create_app
    from app.config import TestConfig
    class Config(TestConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'new.sqlite').as_posix()}"
    application = create_app(Config)
    with application.app_context():
        db.create_all()
        seed_defaults()
        assert [row.number for row in Wristband.query.order_by(Wristband.number)] == [f'{n:03}' for n in range(1,101)]
        assert CatalogItem.query.filter(CatalogItem.reference_code.is_not(None)).count() == 42
        assert CatalogItem.query.filter_by(reference_code='ticket.adult').one().price == 15
        assert CatalogItem.query.filter_by(reference_code='ticket.child').one().price == 10
        assert all(row.stock_quantity == 0 for row in CatalogItem.query.filter_by(stock_tracked=True))
        assert CatalogItem.query.filter_by(reference_code='package.A').one().package_definition['schema'] == 1
        db.session.remove(); db.engine.dispose()
