import { describe, expect, it } from 'vitest'
import { refreshDomainsForEvent } from './events'

describe('mobile realtime domains', () => {
  it('routes sales events to only the affected mobile data', () => {
    expect(refreshDomainsForEvent('visit.changed')).toEqual(['orders', 'reports'])
    expect(refreshDomainsForEvent('inventory.changed')).toEqual(['orders', 'inventory', 'reports'])
    expect(refreshDomainsForEvent('catalog.changed')).toEqual(['orders'])
    expect(refreshDomainsForEvent('unknown')).toEqual([])
  })
})
