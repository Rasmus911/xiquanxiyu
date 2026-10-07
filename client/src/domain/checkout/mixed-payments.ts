export interface MixedPayment { method: string; amount: number | null; reference: string }
const METHODS = new Set(['cash', 'wechat', 'alipay', 'balance'])

function cents(value: string | number | null): number {
  if (value === null || value === '') return 0
  const text = String(value)
  if (!/^\d+(\.\d{1,2})?$/.test(text)) throw new Error('请输入非负金额，最多两位小数')
  const [whole, fraction = ''] = text.split('.')
  const result = Number(whole) * 100 + Number(fraction.padEnd(2, '0'))
  if (!Number.isSafeInteger(result) || result > 999999999999) throw new Error('金额超出允许范围')
  return result
}
const money = (value: number) => (value / 100).toFixed(2)

export function paymentSummary(total: string, rows: MixedPayment[]) {
  try {
    const due = cents(total)
    const paid = rows.reduce((sum, row) => {
      if (!METHODS.has(row.method)) throw new Error('支付方式无效')
      return sum + cents(row.amount)
    }, 0)
    return { valid: true, balanced: paid === due, paid: money(paid),
      remaining: money(Math.max(0, due - paid)), overpaid: money(Math.max(0, paid - due)) }
  } catch {
    return { valid: false, balanced: false, paid: '0.00', remaining: total, overpaid: '0.00' }
  }
}

export function fillRemaining(total: string, rows: MixedPayment[], index: number, memberBalance?: string) {
  const row = rows[index]
  if (!row) return
  const others = rows.reduce((sum, value, i) => sum + (i === index ? 0 : cents(value.amount)), 0)
  let available = Math.max(0, cents(total) - others)
  if (row.method === 'balance') available = Math.min(available, cents(memberBalance || '0.00'))
  row.amount = available / 100
}

export function applyMemberBalance(total: string, rows: MixedPayment[], balance: string, automaticCash: boolean) {
  if (automaticCash && rows.filter(row => row.method !== 'cash').every(row => !row.amount)
      && cents(rows.find(row => row.method === 'cash')?.amount ?? 0) === cents(total)) {
    const cash = rows.find(row => row.method === 'cash')
    if (cash) cash.amount = 0
  }
  fillRemaining(total, rows, rows.findIndex(row => row.method === 'balance'), balance)
}

export function paymentPayload(rows: MixedPayment[]) {
  return rows.flatMap(row => {
    if (!METHODS.has(row.method)) throw new Error('支付方式无效')
    const amount = cents(row.amount)
    return amount > 0 ? [{ method: row.method, amount: money(amount), reference: row.reference }] : []
  })
}
