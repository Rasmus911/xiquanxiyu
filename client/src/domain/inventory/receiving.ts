function scaled(raw: string, digits: number): bigint | null {
  const value = raw.trim()
  if (!new RegExp(`^\\d+(?:\\.\\d{1,${digits}})?$`).test(value) || value.length > 24) return null
  const [whole, fraction = ''] = value.split('.')
  return BigInt(whole!) * 10n ** BigInt(digits) + BigInt(fraction.padEnd(digits, '0'))
}
function fixed(value: bigint, digits: number) {
  const text = value.toString().padStart(digits + 1, '0')
  return `${text.slice(0, -digits)}.${text.slice(-digits)}`
}
export function costPreview(quantity: string, price: string, factor: string) {
  const q=scaled(quantity,3), p=scaled(price,2), f=scaled(factor,3)
  if(q===null||p===null||f===null||f<=0n||q<=0n||p>=1000000000000n) return null
  const cents=(q*p+500n)/1000n
  if(cents>=1000000000000n) return null
  return {total:fixed(cents,2),baseUnit:fixed((p*10000000n+f/2n)/f,6)}
}
export function warningPreview(baseQuantity: string) {
  const value=scaled(baseQuantity,3)
  return value===null?'—':fixed((value*15n+99n)/100n,3)
}
export const receivingReasons: Record<string,string[]> = {
  purchase:['采购入库'],opening:['期初库存','补录期初'],return:['误出库退回','客人退回未使用耗材'],
  loss:['破损报损','过期报损'],adjust:['盘点补入','盘点减少','数量录入纠正'],
}
export const clearReasons=['误开牌，客人未入场','测试','客人取消入场']
