export type MobileRefreshDomain = 'orders' | 'inventory' | 'reports'

const EVENTS: Record<string, MobileRefreshDomain[]> = {
  'wristbands.changed': ['orders'],
  'visit.changed': ['orders', 'reports'],
  'catalog.changed': ['orders'],
  'inventory.changed': ['orders', 'inventory', 'reports'],
  'checkout.completed': ['orders', 'reports'],
  'checkout.refunded': ['orders', 'reports'],
  'member.changed': ['reports'],
}

export function refreshDomainsForEvent(event: string): MobileRefreshDomain[] {
  return [...(EVENTS[event] || [])]
}
