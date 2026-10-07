import { clearPendingRequestKey, pendingRequestKey } from '../requests/pending-key'

const CHECKOUT_SCOPE = 'checkout:complete'

export interface CheckoutPaymentFingerprint {
  method: string
  amount: number
  reference?: string
}

export function checkoutFingerprint(
  visitIds: string[],
  payments: CheckoutPaymentFingerprint[],
  memberId: string,
) {
  const visits = [...new Set(visitIds)].sort().join(',')
  const paymentRows = payments
    .map((row) => `${row.method}:${Number(row.amount || 0).toFixed(2)}:${row.reference || ''}`)
    .sort()
    .join('|')
  return `${visits}#${paymentRows}#${memberId}`
}

export function checkoutRequestKey(fingerprint: string) {
  return pendingRequestKey(CHECKOUT_SCOPE, fingerprint)
}

export function clearCheckoutRequest() {
  clearPendingRequestKey(CHECKOUT_SCOPE)
}
