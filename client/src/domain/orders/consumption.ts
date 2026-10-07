import type { ManualConsumption } from '../../types'

export function buildManualConsumption(rows: readonly ManualConsumption[]) {
  const ids = new Set<string>()
  for (const row of rows) {
    if (!row.stock_item_id || ids.has(row.stock_item_id)) throw new Error('请选择耗材，且同一项目不可重复选择同一种耗材')
    if (!/^\d+(\.\d{1,3})?$/.test(row.quantity) || !Number.isFinite(Number(row.quantity)) || Number(row.quantity) <= 0) {
      throw new Error('耗材总量须大于零，最多三位小数')
    }
    ids.add(row.stock_item_id)
  }
  return { inventory_mode: 'manual' as const, inventory_consumption: rows.map(row => ({ ...row })) }
}
