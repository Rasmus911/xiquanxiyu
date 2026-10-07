import { beforeEach, describe, expect, it } from 'vitest'
import { checkoutFingerprint, checkoutRequestKey, clearCheckoutRequest } from './checkout-request'

describe('checkout retry request', () => {
  beforeEach(() => sessionStorage.clear())

  it('changes fingerprint when selected visits or payment amounts change', () => {
    const base = checkoutFingerprint(['v2', 'v1'], [{ method: 'cash', amount: 20 }], '')
    expect(base).toBe(checkoutFingerprint(['v1', 'v2'], [{ method: 'cash', amount: 20 }], ''))
    expect(base).not.toBe(checkoutFingerprint(['v1'], [{ method: 'cash', amount: 20 }], ''))
    expect(base).not.toBe(checkoutFingerprint(['v1', 'v2'], [{ method: 'cash', amount: 21 }], ''))
  })

  it('keeps the same key through a timeout and clears only after success', () => {
    const fingerprint = checkoutFingerprint(['v1'], [{ method: 'cash', amount: 20 }], '')
    const first = checkoutRequestKey(fingerprint)
    expect(checkoutRequestKey(fingerprint)).toBe(first)
    clearCheckoutRequest()
    expect(checkoutRequestKey(fingerprint)).not.toBe(first)
  })
})
