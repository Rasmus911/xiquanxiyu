from decimal import Decimal as D

import pytest

from app.package_billing import BillingLine, PackageSlot, allocate_inclusions, line_net_total


def test_package_a_and_water_net_is_48_not_gross_sum():
    lines=[BillingLine('ticket','adult',D(1),D(15),0),BillingLine('scrub','scrub',D(1),D(10),1),
        BillingLine('cup','cup',D(1),D(15),2),BillingLine('water','water',D(1),D(3),3)]
    slots=[PackageSlot(('adult','child'),D(1)),PackageSlot(('scrub',),D(1)),PackageSlot(('cup',),D(1))]
    covered=allocate_inclusions(lines,slots)
    assert covered=={'ticket':D(1),'scrub':D(1),'cup':D(1),'water':D(0)}
    assert D(45)+sum(line_net_total(line,covered[line.id]) for line in lines)==D('48.00')


def test_quantities_remain_physical_while_only_one_unit_is_included():
    lines=[BillingLine('cup','cup',D(2),D(15),0),BillingLine('supplies','supplies',D(3),D(7),1)]
    coverage=allocate_inclusions(lines,[PackageSlot(('cup',),D(1)),PackageSlot(('supplies',),D(1))])
    assert coverage=={'cup':D(1),'supplies':D(1)}
    assert [line.quantity for line in lines]==[D(2),D(3)]
    assert [line_net_total(line,coverage[line.id]) for line in lines]==[D('15.00'),D('14.00')]
    assert allocate_inclusions(lines,[])=={'cup':D(0),'supplies':D(0)}


def test_shared_ticket_slot_cannot_cover_both_adult_and_child_or_a_later_line():
    lines=[BillingLine('later','adult',D(1),D(15),4),BillingLine('first','child',D(1),D(10),0),
        BillingLine('middle','child',D(1),D(10),2)]
    assert allocate_inclusions(lines,[PackageSlot(('adult','child'),D(1))])=={
        'later':D(0),'first':D(1),'middle':D(0)}


@pytest.mark.parametrize('quantity,price',[(D(0),D(1)),(D(-1),D(1)),(D(1),D(-1)),
    (D('NaN'),D(1)),(D(1),D('Infinity')),(1.1,D(3))])
def test_invalid_line_numbers_cannot_enter_money_calculation(quantity,price):
    with pytest.raises(ValueError):
        allocate_inclusions([BillingLine('x','x',quantity,price,0)],[])


@pytest.mark.parametrize('covered',[D(-1),D(2),D('NaN'),D('Infinity')])
def test_included_quantity_must_be_finite_and_within_actual_quantity(covered):
    with pytest.raises(ValueError): line_net_total(BillingLine('x','x',D(1),D(7),0),covered)


def test_duplicate_lines_or_overlapping_slots_cannot_double_cover():
    line=BillingLine('x','x',D(1),D(7),0)
    with pytest.raises(ValueError): allocate_inclusions([line,line],[])
    with pytest.raises(ValueError): allocate_inclusions([line],[PackageSlot(('x',),D(1)),PackageSlot(('x','y'),D(1))])
    with pytest.raises(ValueError): allocate_inclusions([line],[PackageSlot(('x','x'),D(1))])
    with pytest.raises(ValueError): allocate_inclusions([line],[PackageSlot((),D(1))])
    with pytest.raises(ValueError): allocate_inclusions([line],[PackageSlot(('x',),D(0))])


def test_money_uses_decimal_and_two_places_without_negative_net():
    line=BillingLine('fraction','x',D('0.333'),D('3.00'),0)
    assert line_net_total(line,D(0))==D('1.00')
    assert str(line_net_total(line,D('0.333')))=='0.00'
