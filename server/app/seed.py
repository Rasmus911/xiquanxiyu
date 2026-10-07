"""Non-destructive defaults. Existing business data requires explicit maintenance."""
from decimal import Decimal

from .extensions import db
from .models import CatalogItem, SystemSetting, Wristband

MALE_WRISTBAND_NUMBERS = tuple(f'{number:03}' for number in range(1,51))
FEMALE_WRISTBAND_NUMBERS = tuple(f'{number:03}' for number in range(51,101))
DEFAULT_WRISTBAND_NUMBERS = MALE_WRISTBAND_NUMBERS + FEMALE_WRISTBAND_NUMBERS
DEFAULT_SETTINGS = {
    'store_name': ('溪泉洗浴', '小票和系统显示的店名'),
    'lost_wristband_fee': ('20.00', '手牌挂失赔偿金额'),
    'allow_negative_stock': (False, '是否允许商品库存为负数'),
    'require_open_shift': (False, '已停用交接班流程'),
}


def seed_defaults():
    from .business_period import ensure_business_state
    from .operations_upgrade import apply_formal_catalog, retire_legacy_wristbands_and_create_hundred
    ensure_business_state(db.session)
    for key,(value,description) in DEFAULT_SETTINGS.items():
        if not SystemSetting.query.filter_by(key=key).first():
            db.session.add(SystemSetting(key=key,value=value,description=description))
    # Never refill holes, reactivate retired rows, reset stock or rewrite prices.
    if not Wristband.query.first():
        retire_legacy_wristbands_and_create_hundred(db.session)
    if not CatalogItem.query.first():
        apply_formal_catalog(db.session)
        db.session.add(CatalogItem(kind='compensation',category='赔偿',name='手牌挂失赔偿',price=Decimal('20.00')))
    db.session.commit()
