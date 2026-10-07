import type { MobileCatalogItem } from './types'

export type QuantityMap = Record<string, number>
export type ProductQuantityItem = Pick<MobileCatalogItem, 'id' | 'stock_tracked' | 'stock_quantity'>

export function toggleServiceQuantity(quantities: QuantityMap, itemId: string): QuantityMap {
  return { ...quantities, [itemId]: quantities[itemId] ? 0 : 1 }
}

export function changeProductQuantity(
  quantities: QuantityMap,
  item: ProductQuantityItem,
  delta: number,
): QuantityMap {
  const current = quantities[item.id] || 0
  const maximum = 99
  const next = Math.max(0, Math.min(maximum, current + delta))
  return { ...quantities, [item.id]: next }
}

export function selectedOrderRows(catalog: MobileCatalogItem[], quantities: QuantityMap) {
  return catalog
    .filter((item) => (quantities[item.id] || 0) > 0)
    .map((item) => ({ ...item, quantity: quantities[item.id] }))
}

export function clampOrderQuantities(
  catalog: MobileCatalogItem[],
  quantities: QuantityMap,
): QuantityMap {
  const next: QuantityMap = {}
  for (const item of catalog) {
    if (item.is_active === false) continue
    const requested = Math.max(0, Math.floor(quantities[item.id] || 0))
    if (!requested) continue
    const maximum = item.kind === 'service' || item.kind === 'package'
      ? 1
      : 99
    const available = Math.min(requested, maximum)
    if (available > 0) next[item.id] = available
  }
  return next
}

export function selectionTotals(rows: Array<{ price: string; quantity: number }>) {
  return rows.reduce((result, row) => ({
    kinds: result.kinds + 1,
    units: result.units + row.quantity,
    amount: result.amount + Number(row.price) * row.quantity,
  }), { kinds: 0, units: 0, amount: 0 })
}

export function switchVisitSelection(
  currentVisitId: string,
  nextVisitId: string,
  quantities: QuantityMap,
) {
  const changed = currentVisitId !== nextVisitId
  return {
    changed,
    visitId: nextVisitId,
    quantities: changed ? {} : quantities,
  }
}
