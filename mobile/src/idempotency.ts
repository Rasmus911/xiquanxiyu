const PENDING_FINGERPRINT_KEY = 'xiquan_mobile_pending_order_fingerprint'
const PENDING_REQUEST_KEY = 'xiquan_mobile_pending_order_key'

export interface PendingOrderItem {
  catalog_item_id: string
  quantity: number | string
  inventory_mode?: 'manual'
  inventory_consumption?: import('./types').Consumption[]
}

export function orderFingerprint(visitId: string, items: PendingOrderItem[]) {
  const normalizedItems = [...items]
    .map((item) => ({ ...item, ...(item.inventory_consumption ? { inventory_consumption: [...item.inventory_consumption].sort((a,b) => a.stock_item_id.localeCompare(b.stock_item_id)) } : {}) }))
    .sort((left, right) => left.catalog_item_id.localeCompare(right.catalog_item_id))
  return JSON.stringify({ visit_id: visitId, items: normalizedItems })
}

export function pendingOrderKey(visitId: string, items: PendingOrderItem[]) {
  const fingerprint = orderFingerprint(visitId, items)
  const existingFingerprint = localStorage.getItem(PENDING_FINGERPRINT_KEY)
  const existingKey = localStorage.getItem(PENDING_REQUEST_KEY)
  if (existingFingerprint === fingerprint && existingKey) return existingKey

  const key = crypto.randomUUID()
  localStorage.setItem(PENDING_FINGERPRINT_KEY, fingerprint)
  localStorage.setItem(PENDING_REQUEST_KEY, key)
  return key
}

export function clearPendingOrderKey() {
  localStorage.removeItem(PENDING_FINGERPRINT_KEY)
  localStorage.removeItem(PENDING_REQUEST_KEY)
}

export function pendingOperationKey(scope: string, fingerprint: string) {
  const storageKey = `xiquan_mobile_pending_operation_${scope}`
  try {
    const existing = JSON.parse(localStorage.getItem(storageKey) || 'null') as { fingerprint: string; key: string } | null
    if (existing?.fingerprint === fingerprint && existing.key) return existing.key
  } catch { localStorage.removeItem(storageKey) }
  const key = crypto.randomUUID()
  localStorage.setItem(storageKey, JSON.stringify({ fingerprint, key }))
  return key
}

export function clearPendingOperationKey(scope: string) {
  localStorage.removeItem(`xiquan_mobile_pending_operation_${scope}`)
}
