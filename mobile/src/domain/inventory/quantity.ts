// Exact fixed-decimal validation mirrors the server's stock quantity range/scale.
const MAX_THOUSANDTHS = 1000000000000n
function thousandths(value: string): bigint | null {
  const normalized = value.trim()
  if (!/^\d{1,9}(\.\d{1,3})?$/.test(normalized)) return null
  const [whole, fraction = ''] = normalized.split('.')
  const parsed = BigInt(whole!) * 1000n + BigInt(fraction.padEnd(3, '0'))
  return parsed < MAX_THOUSANDTHS ? parsed : null
}
export function validQuantity(value: string, positive = true) {
  const parsed = thousandths(value)
  return parsed !== null && (!positive || parsed > 0n)
}
function convert(quantity: string, unit: string, factor: string, allowZero: boolean) {
  const input = thousandths(quantity); const conversion = unit === 'package' ? thousandths(factor) : 1000n
  if (input === null || (!allowZero && input === 0n)) return {error:`数量须为${allowZero?'非负':'正'}数字，最多三位小数且小于10亿`,quantity:null}
  if (!['base','package'].includes(unit) || conversion === null || conversion <= 0n) return {error:'包装换算须为正数，最多三位小数且小于10亿',quantity:null}
  const product = input * conversion
  if (product % 1000n !== 0n) return {error:'折算数量超出三位小数，请调整数量或包装规格',quantity:null}
  const scaled = product / 1000n
  if (scaled >= MAX_THOUSANDTHS) return {error:'折算数量须小于10亿，请调整数量或包装规格',quantity:null}
  return {error:'',quantity:scaled}
}
export function stockConversionError(quantity: string, unit: string, factor: string, allowZero = false) {
  return convert(quantity,unit,factor,allowZero).error
}
export function previewStockQuantity(quantity: string, unit: string, factor: string) {
  const {quantity:scaled} = convert(quantity,unit,factor,true)
  if (scaled === null) return '—'
  return `${scaled / 1000n}.${String(scaled % 1000n).padStart(3, '0')}`
}
