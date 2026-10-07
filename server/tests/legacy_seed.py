"""Explicit pre-upgrade data fixture, never used by application startup."""
from decimal import Decimal

from app.extensions import db
from app.models import CatalogItem, SystemSetting, Wristband

MALE_WRISTBAND_NUMBERS = tuple(str(number) for number in range(8001, 8061))
FEMALE_WRISTBAND_NUMBERS = tuple(str(number) for number in range(9001, 9061))
DEFAULT_WRISTBAND_NUMBERS = MALE_WRISTBAND_NUMBERS + FEMALE_WRISTBAND_NUMBERS

DEFAULT_SETTINGS = {
    "store_name": ("溪泉洗浴", "小票和系统显示的店名"),
    "lost_wristband_fee": ("20.00", "手牌挂失赔偿金额"),
    "allow_negative_stock": (False, "是否允许商品库存为负数"),
    "require_open_shift": (False, "已停用交接班流程"),
}

# 参考承德地区常见大众洗浴消费习惯的初始项目，仅作为可编辑模板。
DEFAULT_CATALOG = (
    ("service", "搓澡助浴", "传统搓澡", "30.00", False, 10, "scrub"),
    ("service", "搓澡助浴", "牛奶浴", "38.00", False, 20, "scrub"),
    ("service", "搓澡助浴", "盐浴", "38.00", False, 30, "scrub"),
    ("service", "搓澡助浴", "芦荟浴", "38.00", False, 40, "scrub"),
    ("service", "搓澡助浴", "醋搓", "35.00", False, 50, "scrub"),
    ("service", "搓澡助浴", "蜂蜜浴", "48.00", False, 60, "scrub"),
    ("service", "组合项目", "二合一（搓澡+牛奶）", "58.00", False, 70, "scrub"),
    ("service", "组合项目", "三合一（搓澡+牛奶+盐）", "78.00", False, 80, "scrub"),
    ("service", "理疗按摩", "刮痧", "30.00", False, 90, "rest"),
    ("service", "理疗按摩", "拔罐", "30.00", False, 100, "rest"),
    ("service", "理疗按摩", "修脚", "30.00", False, 110, "rest"),
    ("service", "理疗按摩", "足疗（60分钟）", "68.00", False, 120, "rest"),
    ("service", "理疗按摩", "全身按摩（60分钟）", "128.00", False, 130, "rest"),
    ("product", "洗浴用品", "一次性搓澡巾", "5.00", True, 210, "scrub"),
    ("product", "洗浴用品", "一次性毛巾", "8.00", True, 220, "scrub"),
    ("product", "洗浴用品", "牙刷牙膏套装", "3.00", True, 230, "scrub"),
    ("product", "洗浴用品", "香皂", "3.00", True, 240, "scrub"),
    ("product", "饮品", "矿泉水", "3.00", True, 310, "rest"),
    ("product", "饮品", "可乐", "5.00", True, 320, "rest"),
    ("product", "饮品", "雪碧", "5.00", True, 330, "rest"),
    ("product", "饮品", "冰红茶", "5.00", True, 340, "rest"),
    ("product", "饮品", "王老吉", "6.00", True, 350, "rest"),
    ("product", "饮品", "红牛", "8.00", True, 360, "rest"),
    ("product", "承德特色饮品", "承德杏仁露", "6.00", True, 370, "rest"),
    ("product", "承德特色饮品", "山楂汁", "6.00", True, 380, "rest"),
    ("product", "食品", "方便面", "6.00", True, 410, "rest"),
    ("product", "食品", "火腿肠", "3.00", True, 420, "rest"),
    ("product", "食品", "茶叶蛋", "2.00", True, 430, "rest"),
)


def seed_legacy_defaults():
    for key, (value, description) in DEFAULT_SETTINGS.items():
        setting = SystemSetting.query.filter_by(key=key).first()
        if not setting:
            db.session.add(SystemSetting(key=key, value=value, description=description))
        elif key == "require_open_shift":
            setting.value = False
            setting.description = description

    existing_wristbands = {
        row.number for row in Wristband.query.filter(Wristband.number.in_(DEFAULT_WRISTBAND_NUMBERS)).all()
    }
    for number in DEFAULT_WRISTBAND_NUMBERS:
        if number not in existing_wristbands:
            from app.serializers import wristband_area
            db.session.add(Wristband(number=number, bath_area=wristband_area(number)))

    if not CatalogItem.query.filter_by(kind="ticket").first():
        db.session.add(
            CatalogItem(
                kind="ticket",
                category="门票",
                name="基础门票",
                price=Decimal("0.00"),
                sort_order=0,
            )
        )
    if not CatalogItem.query.filter_by(kind="compensation").first():
        db.session.add(
            CatalogItem(
                kind="compensation",
                category="赔偿",
                name="手牌挂失赔偿",
                price=Decimal("20.00"),
                sort_order=0,
            )
        )
    for kind, category, name, price, stock_tracked, sort_order, mobile_scope in DEFAULT_CATALOG:
        if not CatalogItem.query.filter_by(kind=kind, name=name).first():
            db.session.add(
                CatalogItem(
                    kind=kind,
                    category=category,
                    name=name,
                    mobile_scope=mobile_scope,
                    price=Decimal(price),
                    stock_tracked=stock_tracked,
                    stock_quantity=Decimal("10") if stock_tracked else Decimal("0"),
                    low_stock_threshold=Decimal("5") if stock_tracked else Decimal("0"),
                    sort_order=sort_order,
                )
            )
    db.session.commit()
    from app.business_period import ensure_business_state

    ensure_business_state(db.session)
    db.session.commit()
