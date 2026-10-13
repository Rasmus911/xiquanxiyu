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

  it('includes pass, people, member, binding, method and surname in the stable checkout identity', () => {
    const rows = [{ method: 'cash', amount: 10 }]
    const benefits = { pass_use: { member_pass_id: 'p1', visit_ids: ['v2', 'v1'] },
      member_verification: { method: 'card' as const, card_binding_id: 'c1', surname_confirmed: true } }
    const base = checkoutFingerprint(['v1', 'v2'], rows, 'm1', benefits)
    expect(base).toBe(checkoutFingerprint(['v2', 'v1'], rows, 'm1', {
      ...benefits, pass_use: { ...benefits.pass_use, visit_ids: ['v1', 'v2'] } }))
    for (const changed of [
      { ...benefits, pass_use: null },
      { ...benefits, pass_use: { ...benefits.pass_use, member_pass_id: 'p2' } },
      { ...benefits, pass_use: { ...benefits.pass_use, visit_ids: ['v1'] } },
      { ...benefits, member_verification: { ...benefits.member_verification, card_binding_id: 'c2' } },
      { ...benefits, member_verification: { ...benefits.member_verification, surname_confirmed: false } },
      { ...benefits, member_verification: { method: 'phone' as const, surname_confirmed: true } },
    ]) expect(base).not.toBe(checkoutFingerprint(['v1', 'v2'], rows, 'm1', changed))
    expect(base).not.toBe(checkoutFingerprint(['v1', 'v2'], rows, 'm2', benefits))
    expect(checkoutFingerprint(['v1'], rows, null)).toBe(checkoutFingerprint(['v1'], rows, null, { pass_use: null, member_verification: null }))
  })
})
