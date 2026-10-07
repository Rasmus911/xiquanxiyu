from decimal import Decimal

from app.catalog_defaults import formal_catalog_specs


def test_exact_approved_codes_prices_and_names():
    expected = {
        'ticket.adult': ('门票',15), 'ticket.child': ('儿童门票（一米以下）',10),
        'bath.scrub': ('搓澡',10), 'bath.towel': ('澡巾',6), 'bath.supplies': ('备品',7),
        'bath.mud': ('搓泥宝',10), 'bath.wine': ('红酒搓',10), 'bath.vinegar': ('醋搓',10),
        'bath.back': ('敲背',20), 'bath.egg': ('蛋奶蜜',35), 'bath.gua': ('男/女浴刮痧',15),
        'bath.roll': ('男/女浴擀筋',20), 'bath.cup': ('男/女浴拔罐',15),
        'bath.combo2': ('二合一',15), 'bath.combo3': ('三合一',20), 'bath.combo5': ('五合一',30),
        'bath.combo6': ('六合一',40), 'bath.combo7': ('七合一',50), 'bath.aloe': ('芦荟灌肤',58),
        'rest.ear': ('采耳',20), 'rest.cup': ('三楼拔罐',20), 'rest.leg': ('揉腿（20分钟）',30),
        'rest.step': ('踩背（20分钟）',30), 'rest.foot': ('精品足疗（20分钟）',30),
        'rest.oilback': ('精油开背（30分钟）',98), 'rest.thai': ('泰式按摩（60分钟）',128),
        'rest.oilbody': ('全身推油（80分钟）',208), 'rest.earcandle': ('耳烛',20),
        'rest.roll': ('三楼擀筋',30), 'rest.abdomen': ('腹疗（20分钟）',30), 'rest.head': ('头疗（20分钟）',30),
        'rest.hongkong': ('港式按摩（40分钟）',68), 'rest.classic': ('溪泉经典（50分钟）',100),
        'rest.american': ('美式按摩（60分钟）',168), 'rest.supreme': ('溪泉至尊（120分钟）',268),
        'package.A': ('套票A（门票+搓澡+单盐（奶）+拔罐+备品）',45),
        'package.B': ('套票B（门票+搓澡+二合一（奶）+拔罐）',48),
        'package.C': ('套票C（门票+搓澡+五合一（奶）+搓泥宝）',55),
        'package.D': ('套票D（门票+搓澡+足疗+踩背+备品）',78),
        'package.E': ('套票E（门票+搓澡+足疗+港式按摩+备品）',108),
        'package.F': ('套票F（门票+搓澡+搓泥宝+足疗+泰式按摩+备品）',188),
        'package.G': ('套票G（门票+搓澡+搓泥宝+足疗+美式按摩+备品）',218),
    }
    specs = formal_catalog_specs()
    assert len(specs) == 42
    assert {item.reference_code: (item.name, item.price) for item in specs} == {
        code: (name, Decimal(price)) for code, (name, price) in expected.items()}


def test_permissions_stock_and_package_slots_are_explicit_and_immutable():
    specs = formal_catalog_specs()
    by_code = {item.reference_code: item for item in specs}
    assert {item.reference_code for item in specs if item.stock_tracked} == set()
    assert all(by_code[code].kind=='service' for code in ('bath.towel','bath.supplies','bath.mud'))
    assert all(item.mobile_scope == 'scrub' for item in specs if item.reference_code.startswith('bath.'))
    assert all(item.mobile_scope == 'rest' for item in specs if item.reference_code.startswith('rest.'))
    expected = {
        'A': ('bath.scrub','bath.cup','bath.supplies'),
        'B': ('bath.scrub','bath.combo2','bath.cup'),
        'C': ('bath.scrub','bath.combo5','bath.mud'),
        'D': ('bath.scrub','rest.foot','rest.step','bath.supplies'),
        'E': ('bath.scrub','rest.foot','rest.hongkong','bath.supplies'),
        'F': ('bath.scrub','bath.mud','rest.foot','rest.thai','bath.supplies'),
        'G': ('bath.scrub','bath.mud','rest.foot','rest.american','bath.supplies'),
    }
    for code, slots in expected.items():
        item = by_code['package.' + code]
        assert item.kind == 'package' and item.mobile_scope == 'frontdesk'
        assert item.package_slots == (('ticket.adult','ticket.child'),) + tuple((id_,) for id_ in slots)
        assert item.display_contents
    assert not any(item.name in ('单盐','单奶','单盐（奶）') for item in specs)
