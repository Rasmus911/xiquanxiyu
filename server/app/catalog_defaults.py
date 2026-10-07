"""Approved October catalog, immutable values only; no database side effects."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CatalogSpec:
    reference_code: str
    kind: str
    category: str
    name: str
    price: Decimal
    mobile_scope: str
    stock_tracked: bool = False
    sort_order: int = 0
    package_slots: tuple[tuple[str, ...], ...] = ()
    display_contents: tuple[str, ...] = ()


def formal_catalog_specs() -> tuple[CatalogSpec, ...]:
    tickets = [('adult', '门票', '15'), ('child', '儿童门票（一米以下）', '10')]
    bath = [
        ('scrub','搓澡','10'), ('towel','澡巾','6'), ('supplies','备品','7'),
        ('mud','搓泥宝','10'), ('wine','红酒搓','10'), ('vinegar','醋搓','10'),
        ('back','敲背','20'), ('egg','蛋奶蜜','35'), ('gua','男/女浴刮痧','15'),
        ('roll','男/女浴擀筋','20'), ('cup','男/女浴拔罐','15'), ('combo2','二合一','15'),
        ('combo3','三合一','20'), ('combo5','五合一','30'), ('combo6','六合一','40'),
        ('combo7','七合一','50'), ('aloe','芦荟灌肤','58'),
    ]
    rest = [
        ('ear','采耳','20'), ('cup','三楼拔罐','20'), ('leg','揉腿（20分钟）','30'),
        ('step','踩背（20分钟）','30'), ('foot','精品足疗（20分钟）','30'),
        ('oilback','精油开背（30分钟）','98'), ('thai','泰式按摩（60分钟）','128'),
        ('oilbody','全身推油（80分钟）','208'), ('earcandle','耳烛','20'), ('roll','三楼擀筋','30'),
        ('abdomen','腹疗（20分钟）','30'), ('head','头疗（20分钟）','30'),
        ('hongkong','港式按摩（40分钟）','68'), ('classic','溪泉经典（50分钟）','100'),
        ('american','美式按摩（60分钟）','168'), ('supreme','溪泉至尊（120分钟）','268'),
    ]
    packages = [
        ('A','45',('门票','搓澡','单盐（奶）','拔罐','备品'),('bath.scrub','bath.cup','bath.supplies')),
        ('B','48',('门票','搓澡','二合一（奶）','拔罐'),('bath.scrub','bath.combo2','bath.cup')),
        ('C','55',('门票','搓澡','五合一（奶）','搓泥宝'),('bath.scrub','bath.combo5','bath.mud')),
        ('D','78',('门票','搓澡','足疗','踩背','备品'),('bath.scrub','rest.foot','rest.step','bath.supplies')),
        ('E','108',('门票','搓澡','足疗','港式按摩','备品'),('bath.scrub','rest.foot','rest.hongkong','bath.supplies')),
        ('F','188',('门票','搓澡','搓泥宝','足疗','泰式按摩','备品'),('bath.scrub','bath.mud','rest.foot','rest.thai','bath.supplies')),
        ('G','218',('门票','搓澡','搓泥宝','足疗','美式按摩','备品'),('bath.scrub','bath.mud','rest.foot','rest.american','bath.supplies')),
    ]
    result = []
    for code, name, price in tickets:
        result.append(CatalogSpec('ticket.'+code, 'ticket', '门票', name, Decimal(price), 'frontdesk'))
    for prefix, category, scope, rows in [('bath','洗浴','scrub',bath), ('rest','按摩','rest',rest)]:
        for code, name, price in rows:
            result.append(CatalogSpec(prefix+'.'+code, 'service', category,
                name, Decimal(price), scope, False, (len(result)+1)*10))
    for code, price, contents, slots in packages:
        result.append(CatalogSpec('package.'+code, 'package', '套票', '套票'+code+'（'+'+'.join(contents)+'）',
            Decimal(price), 'frontdesk', False, (len(result)+1)*10,
            (('ticket.adult','ticket.child'),) + tuple((id_,) for id_ in slots), contents))
    return tuple(result)
