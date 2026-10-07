// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearPendingOperationKey,
  clearPendingOrderKey,
  pendingOperationKey,
  pendingOrderKey,
} from './idempotency'

describe('mobile order idempotency', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
    vi.spyOn(crypto, 'randomUUID')
      .mockReturnValueOnce('11111111-1111-4111-8111-111111111111')
      .mockReturnValueOnce('22222222-2222-4222-8222-222222222222')
  })

  it('reuses the pending key for the same visit and items', () => {
    const first = pendingOrderKey('visit-1', [
      { catalog_item_id: 'drink', quantity: 2 },
      { catalog_item_id: 'scrub', quantity: 1 },
    ])
    const second = pendingOrderKey('visit-1', [
      { catalog_item_id: 'scrub', quantity: 1 },
      { catalog_item_id: 'drink', quantity: 2 },
    ])

    expect(first).toBe('11111111-1111-4111-8111-111111111111')
    expect(second).toBe(first)
    expect(crypto.randomUUID).toHaveBeenCalledTimes(1)
  })

  it('creates a new key when the visit or selected items change', () => {
    const first = pendingOrderKey('visit-1', [{ catalog_item_id: 'drink', quantity: 1 }])
    const second = pendingOrderKey('visit-1', [{ catalog_item_id: 'drink', quantity: 2 }])

    expect(second).not.toBe(first)
    expect(crypto.randomUUID).toHaveBeenCalledTimes(2)
  })

  it('clears the pending order key after a known result', () => {
    const first = pendingOrderKey('visit-1', [{ catalog_item_id: 'drink', quantity: 1 }])
    clearPendingOrderKey()
    const second = pendingOrderKey('visit-1', [{ catalog_item_id: 'drink', quantity: 1 }])

    expect(second).not.toBe(first)
  })

  it('keeps an inventory operation key across timeout and clears it after confirmation', () => {
    const first = pendingOperationKey('inventory-water', 'water|3|purchase')
    const timeoutRetry = pendingOperationKey('inventory-water', 'water|3|purchase')
    clearPendingOperationKey('inventory-water')
    const confirmedNext = pendingOperationKey('inventory-water', 'water|3|purchase')

    expect(timeoutRetry).toBe(first)
    expect(confirmedNext).not.toBe(first)
  })
})
