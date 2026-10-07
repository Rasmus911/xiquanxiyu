export type RealtimeDomain =
  | 'wristbands'
  | 'visits'
  | 'inventory'
  | 'catalog'
  | 'members'
  | 'checkout'
  | 'reports'

const EVENT_DOMAINS: Record<string, readonly RealtimeDomain[]> = {
  'wristbands.changed': ['wristbands', 'visits'],
  'visit.changed': ['visits', 'wristbands'],
  'inventory.changed': ['inventory'],
  'stock.changed': ['inventory'],
  'catalog.changed': ['catalog'],
  'member.changed': ['members', 'reports'],
  'checkout.completed': ['checkout', 'wristbands', 'visits', 'inventory', 'members', 'reports'],
  'checkout.refunded': ['checkout', 'wristbands', 'visits', 'inventory', 'members', 'reports'],
}

export const REALTIME_EVENT_NAME = 'xiquan:realtime'

export interface RealtimeChangeDetail {
  domains: RealtimeDomain[]
  event: string
  payload?: unknown
}

export interface RealtimeChange {
  domain: RealtimeDomain
  resourceId?: string
  reason: string
}

const RESOURCE_KEYS: Partial<Record<string, string>> = {
  'wristbands.changed': 'wristband_id',
  'visit.changed': 'visit_id',
  'inventory.changed': 'catalog_item_id',
  'stock.changed': 'stock_item_id',
  'catalog.changed': 'item_id',
  'member.changed': 'member_id',
  'checkout.completed': 'settlement_id',
  'checkout.refunded': 'settlement_id',
}

export function mapSocketEvent(event: string, payload: Record<string, unknown> = {}): RealtimeChange | null {
  const domain = domainsForSocketEvent(event)[0]
  if (!domain) return null
  const resourceKey = RESOURCE_KEYS[event]
  const resourceId = resourceKey && typeof payload[resourceKey] === 'string'
    ? String(payload[resourceKey])
    : undefined
  const rawReason = typeof payload.reason === 'string' ? payload.reason : 'changed'
  return { domain, ...(resourceId ? { resourceId } : {}), reason: rawReason }
}

export function domainsForSocketEvent(event: string): RealtimeDomain[] {
  return [...(EVENT_DOMAINS[event] ?? [])]
}

export function isRealtimeDomainAffected(
  subscribed: readonly RealtimeDomain[],
  changed: readonly RealtimeDomain[],
) {
  return subscribed.some((domain) => changed.includes(domain))
}

export function dispatchRealtimeChange(event: string, payload?: unknown) {
  const domains = domainsForSocketEvent(event)
  if (!domains.length) return
  window.dispatchEvent(new CustomEvent<RealtimeChangeDetail>(REALTIME_EVENT_NAME, {
    detail: { domains, event, payload },
  }))
}

export function dispatchRealtimeSnapshot() {
  const domains: RealtimeDomain[] = ['wristbands', 'visits', 'inventory', 'catalog', 'members', 'checkout', 'reports']
  window.dispatchEvent(new CustomEvent<RealtimeChangeDetail>(REALTIME_EVENT_NAME, {
    detail: { domains, event: 'snapshot', payload: { reason: 'reconnected' } },
  }))
}

export function subscribeRealtime(
  domains: readonly RealtimeDomain[],
  callback: (detail: RealtimeChangeDetail) => void,
) {
  const handler = (rawEvent: Event) => {
    const detail = (rawEvent as CustomEvent<RealtimeChangeDetail>).detail
    if (detail && isRealtimeDomainAffected(domains, detail.domains)) callback(detail)
  }
  window.addEventListener(REALTIME_EVENT_NAME, handler)
  return () => window.removeEventListener(REALTIME_EVENT_NAME, handler)
}
