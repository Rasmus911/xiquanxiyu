const SCALE = 1000n
const LIMIT = 1000000000000n // Server quantity range: abs(value) < 1,000,000,000.
interface QuantityOptions { signed?: boolean; zero?: boolean }

function parseQuantity(raw: string, options: QuantityOptions): bigint | undefined {
  const match = /^([+-]?)(\d+)(?:\.(\d{1,3}))?$/.exec(raw.trim())
  if (!match) return undefined
  const whole = match[2]!.replace(/^0+/, '') || '0'
  if (whole.length > 9) return undefined
  const magnitude = BigInt(whole) * SCALE + BigInt((match[3] || '').padEnd(3, '0'))
  const value = match[1] === '-' ? -magnitude : magnitude
  if (magnitude >= LIMIT || (!options.signed && value < 0n) || (!options.zero && value === 0n)) return undefined
  return value
}

// Exact thousandths only. Never round a product that the server will reject.
// Final availability and resulting balance remain server-authoritative.
export function previewStockQuantity(quantity: string, unit: string, factor: string, options: QuantityOptions = {}): string {
  if (unit !== 'base' && unit !== 'package') return '—'
  const value = parseQuantity(quantity, options)
  const multiplier = unit === 'package' ? parseQuantity(factor, {}) : SCALE
  if (value === undefined || multiplier === undefined) return '—'
  const product = value * multiplier
  if (product % SCALE !== 0n) return '—'
  const result = product / SCALE
  const magnitude = result < 0n ? -result : result
  if (magnitude >= LIMIT) return '—'
  return `${result < 0n ? '-' : ''}${magnitude / SCALE}.${(magnitude % SCALE).toString().padStart(3, '0')}`
}
