export type CheckoutEntryScope = 'party' | 'selected'

export function initialCheckoutSelection(
  visits: Array<{ visit_id: string }>,
  currentVisitId: string,
  scope: CheckoutEntryScope,
) {
  if (scope === 'selected' && visits.some((visit) => visit.visit_id === currentVisitId)) {
    return [currentVisitId]
  }
  return visits.map((visit) => visit.visit_id)
}

export function toggleCheckoutVisit(selectedIds: string[], visitId: string) {
  if (selectedIds.includes(visitId)) {
    return selectedIds.length === 1 ? selectedIds : selectedIds.filter((id) => id !== visitId)
  }
  return [...selectedIds, visitId]
}
