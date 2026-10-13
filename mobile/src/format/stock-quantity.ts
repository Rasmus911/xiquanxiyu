// Display only: preserve significant fractional digits; never round stock.
export function formatStockQuantity(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const text = String(value)
  if (!/^[+-]?\d+(?:\.\d+)?$/.test(text)) return text
  return text.includes('.') ? text.replace(/0+$/, '').replace(/\.$/, '') : text
}
