export type OrderSelection = Record<string, number>

export function setOrderQuantity(
  selection: OrderSelection,
  itemId: string,
  rawQuantity: number,
  maximum = 99,
): OrderSelection {
  const quantity = Math.min(Math.max(0, Math.floor(Number(rawQuantity) || 0)), maximum)
  const next = { ...selection }
  if (quantity) next[itemId] = quantity
  else delete next[itemId]
  return next
}

export function toggleOrderItem(
  selection: OrderSelection,
  item: { id: string; kind: 'service' | 'product'; maximum?: number },
): OrderSelection {
  const current = selection[item.id] || 0
  if (item.kind === 'service') return setOrderQuantity(selection, item.id, current ? 0 : 1, 1)
  return setOrderQuantity(selection, item.id, current + 1, item.maximum ?? 99)
}

export function orderFingerprint(visitId: string, selection: OrderSelection) {
  const rows = Object.entries(selection)
    .filter(([, quantity]) => quantity > 0)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([itemId, quantity]) => `${itemId}:${quantity}`)
  return [visitId, ...rows].join('|')
}
