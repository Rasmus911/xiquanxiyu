export type MobileTab = 'orders' | 'reports' | 'inventory' | 'catalog'

interface ManagementCapabilities {
  orders_view?: boolean
  reports_view?: boolean
  inventory_manage?: boolean
  reports?: boolean
  inventory_add?: boolean
  catalog_manage?: boolean
}

export function scopedMobileCapabilities(capabilities: ManagementCapabilities | undefined, scope: string[]) {
  const allowed = (permission: string) => scope.includes(permission) || scope.includes('*')
  return {
    orders_view: capabilities?.orders_view === true && allowed('mobile:order'),
    reports_view: (capabilities?.reports_view ?? capabilities?.reports) === true && allowed('report:read'),
    inventory_manage: (capabilities?.inventory_manage ?? capabilities?.inventory_add) === true && allowed('inventory:read') && allowed('inventory:write'),
    catalog_manage: allowed('catalog:read') && allowed('catalog:write'),
  }
}

export function availableMobileTabs(capabilities?: ManagementCapabilities): MobileTab[] {
  const tabs: MobileTab[] = capabilities?.orders_view === true ? ['orders'] : []
  if (capabilities?.reports_view ?? capabilities?.reports) tabs.push('reports')
  if (capabilities?.inventory_manage ?? capabilities?.inventory_add) tabs.push('inventory')
  if (capabilities?.catalog_manage === true) tabs.push('catalog')
  return tabs
}

export function reportRange(days: 1 | 7 | 30, now = new Date()) {
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() - days + 1)
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)
  return { start: start.toISOString(), end: end.toISOString() }
}

export function trendMinWidth(pointCount: number) {
  return pointCount <= 7 ? '100%' : `${pointCount * 38}px`
}

function money(value: unknown) {
  const amount = Number(value || 0)
  return Number.isFinite(amount) ? amount.toFixed(2) : '0.00'
}

export function mobileReportCards(summary: Partial<MobileReportSummary>) {
  const hasBreakdown = summary.stored_value_recharge !== undefined || summary.pass_card_sales !== undefined
  return [
    { label: '营业消费金额', value: money(summary.operating_revenue), subtitle: '结算消费扣除退款' },
    {
      label: '会员充值收款', value: money(summary.member_recharge),
      subtitle: hasBreakdown ? `储值 ¥${money(summary.stored_value_recharge)} · 次卡 ¥${money(summary.pass_card_sales)}` : '储值与次卡收款',
    },
    { label: '实际现金流入', value: money(summary.actual_cash_inflow), subtitle: '不重复计算储值核销' },
    { label: '储值余额核销', value: money(summary.stored_value_consumed), subtitle: '本次不再增加现金流' },
  ]
}
import type { MobileReportSummary } from './types'

