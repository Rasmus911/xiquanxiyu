import { describe, expect, it } from 'vitest'
import { paymentSummary, fillRemaining, applyMemberBalance, paymentPayload } from './mixed-payments'

const rows = () => [
  { method: 'cash', amount: 20, reference: '' },
  { method: 'wechat', amount: 0, reference: '' },
  { method: 'alipay', amount: 40, reference: '' },
  { method: 'balance', amount: 0, reference: '' },
]
describe('mixed payments', () => {
  it('uses only available member balance without replacing entered cash or alipay', () => {
    const payments = rows()
    applyMemberBalance('160.00', payments, '100.00', false)
    expect(payments.map(row => row.amount)).toEqual([20, 0, 40, 100])
    expect(paymentSummary('160.00', payments)).toMatchObject({ paid: '160.00', remaining: '0.00', balanced: true, valid: true })
    expect(paymentPayload(payments)).toEqual([
      { method: 'cash', amount: '20.00', reference: '' },
      { method: 'alipay', amount: '40.00', reference: '' },
      { method: 'balance', amount: '100.00', reference: '' },
    ])
  })
  it('does not erase manually edited cash even if the editor has not blurred yet', () => {
    const payments = rows()
    applyMemberBalance('160.00', payments, '100.00', true)
    expect(payments.map(row => row.amount)).toEqual([20, 0, 40, 100])
  })
  it('reallocates untouched automatic cash to available member balance and leaves the gap visible', () => {
    const payments = rows(); payments[0].amount = 160; payments[2].amount = 0
    applyMemberBalance('160.00', payments, '100.00', true)
    expect(payments.map(row => row.amount)).toEqual([0, 0, 0, 100])
    expect(paymentSummary('160.00', payments).remaining).toBe('60.00')
    fillRemaining('160.00', payments, 2)
    expect(payments.map(row => row.amount)).toEqual([0, 0, 60, 100])
  })
  it('limits balance fill to remaining payable amount and never goes negative on overpayment', () => {
    const payments = rows()
    applyMemberBalance('160.00', payments, '200.00', false)
    expect(payments[3].amount).toBe(100)
    payments[0].amount = 200
    fillRemaining('160.00', payments, 3, '100.00')
    expect(payments[3].amount).toBe(0)
    expect(paymentSummary('160.00', payments)).toMatchObject({ balanced: false, overpaid: '80.00' })
  })
  it('sums exact cents and rejects malformed money instead of treating it as paid', () => {
    const payments = rows(); payments[0].amount = 0.1; payments[2].amount = 0.2
    expect(paymentSummary('0.30', payments)).toMatchObject({ balanced: true, paid: '0.30' })
    for (const invalid of [-1, NaN, Infinity, 0.001]) {
      payments[0].amount = invalid
      expect(paymentSummary('0.30', payments)).toMatchObject({ valid: false, balanced: false })
      expect(() => paymentPayload(payments)).toThrow()
    }
  })
})
