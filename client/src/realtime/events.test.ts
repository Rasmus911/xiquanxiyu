import { describe, expect, it } from 'vitest'
import { domainsForSocketEvent, isRealtimeDomainAffected, mapSocketEvent } from './events'

describe('realtime event routing', () => {
  it('stock changes refresh independent balances and order consumables',()=>{
    expect(domainsForSocketEvent('stock.changed')).toEqual(['inventory'])
    expect(mapSocketEvent('stock.changed',{stock_item_id:'s1'})?.resourceId).toBe('s1')
  })
  it('maps wristband changes to the smallest affected domains', () => {
    expect(domainsForSocketEvent('wristbands.changed')).toEqual(['wristbands', 'visits'])
  })

  it('maps checkout completion to front desk, reports, members and inventory', () => {
    expect(domainsForSocketEvent('checkout.completed')).toEqual([
      'checkout',
      'wristbands',
      'visits',
      'inventory',
      'members',
      'reports',
    ])
  })

  it('normalizes payload identifiers for consumers that need one resource', () => {
    expect(mapSocketEvent('inventory.changed', { catalog_item_id: 'p1' })).toEqual({
      domain: 'inventory',
      resourceId: 'p1',
      reason: 'changed',
    })
    expect(mapSocketEvent('checkout.completed', { settlement_id: 's1' })?.domain).toBe('checkout')
    expect(mapSocketEvent('unknown.event', {})).toBeNull()
  })

  it('ignores unknown transport events instead of refreshing every page', () => {
    expect(domainsForSocketEvent('connect_error')).toEqual([])
  })

  it('checks whether a subscription intersects with an event', () => {
    expect(isRealtimeDomainAffected(['inventory'], ['visits', 'inventory'])).toBe(true)
    expect(isRealtimeDomainAffected(['members'], ['visits', 'inventory'])).toBe(false)
  })
})
