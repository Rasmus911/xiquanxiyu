import { describe, expect, it } from 'vitest'
import { orderFingerprint, setOrderQuantity, toggleOrderItem } from './selection'

describe('order selection', () => {
  it('toggles a service between zero and one', () => {
    expect(toggleOrderItem({}, { id: 's1', kind: 'service' })).toEqual({ s1: 1 })
    expect(toggleOrderItem({ s1: 1 }, { id: 's1', kind: 'service' })).toEqual({})
  })

  it('increments products and applies their stock maximum', () => {
    expect(toggleOrderItem({ p1: 1 }, { id: 'p1', kind: 'product', maximum: 2 })).toEqual({ p1: 2 })
    expect(toggleOrderItem({ p1: 2 }, { id: 'p1', kind: 'product', maximum: 2 })).toEqual({ p1: 2 })
    expect(setOrderQuantity({ p1: 2 }, 'p1', 0, 2)).toEqual({})
  })

  it('creates a stable fingerprint from sorted item quantities', () => {
    expect(orderFingerprint('v1', { p2: 1, p1: 2 })).toBe('v1|p1:2|p2:1')
  })
})
