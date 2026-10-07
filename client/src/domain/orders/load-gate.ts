export interface VisitLoadTicket { visitId: string; sequence: number }
export function createVisitLoadGate() {
  let sequence = 0
  let selected = ''
  return {
    begin(visitId: string): VisitLoadTicket { selected = visitId; return { visitId, sequence: ++sequence } },
    current(ticket: VisitLoadTicket) { return ticket.sequence === sequence && ticket.visitId === selected },
    reset() { sequence++; selected = '' },
  }
}
