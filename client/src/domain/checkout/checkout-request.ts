import { clearPendingRequestKey, pendingRequestKey } from '../requests/pending-key'
import type { CheckoutBenefits } from '../../types'

const CHECKOUT_SCOPE = 'checkout:complete'

export interface CheckoutPaymentFingerprint {
  method: string
  amount: number
  reference?: string
}

export function checkoutFingerprint(
  visitIds: string[],
  payments: CheckoutPaymentFingerprint[],
  memberId: string | null,
  benefits?: CheckoutBenefits,
) {
  const visits = [...new Set(visitIds)].sort().join(',')
  const paymentRows = payments
    .map((row) => `${row.method}:${Number(row.amount || 0).toFixed(2)}:${row.reference || ''}`)
    .sort()
    .join('|')
  const base = `${visits}#${paymentRows}#${memberId}`
  if (!benefits?.pass_use && !benefits?.member_verification) return base
  return `${base}#${JSON.stringify({
    pass_use: benefits.pass_use ? { member_pass_id: benefits.pass_use.member_pass_id,
      visit_ids: [...new Set(benefits.pass_use.visit_ids)].sort() } : null,
    member_verification: benefits.member_verification ? {
      method: benefits.member_verification.method,
      card_binding_id: benefits.member_verification.card_binding_id || null,
      surname_confirmed: benefits.member_verification.surname_confirmed,
    } : null,
  })}`
}

export function checkoutRequestKey(fingerprint: string) {
  return pendingRequestKey(CHECKOUT_SCOPE, fingerprint)
}

export function clearCheckoutRequest() {
  clearPendingRequestKey(CHECKOUT_SCOPE)
}
