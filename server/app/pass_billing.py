"""Select independent tickets by server-recorded quantities and face value."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class TicketCandidate:
    visit_id: str
    order_item_id: str
    amount: Decimal
    quantity: Decimal
    covered_quantity: Decimal
    status: str


def select_pass_tickets(tickets: list[TicketCandidate], visit_ids: list[str]) -> list[TicketCandidate]:
    if not visit_ids or len(set(visit_ids)) != len(visit_ids):
        raise ValueError('抵次手牌不能为空或重复')
    selected = []
    for visit_id in visit_ids:
        rows = [ticket for ticket in tickets if ticket.visit_id == visit_id and ticket.status == 'active']
        if (len(rows) != 1 or rows[0].quantity != 1 or rows[0].covered_quantity != 0
                or rows[0].amount <= 0):
            raise ValueError('每人只能抵扣一张未被套票覆盖的有效独立门票')
        selected.append(rows[0])
    return selected
