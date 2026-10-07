import { describe, expect, it } from 'vitest'
import { availableMobileTabs, mobileReportCards, reportRange, scopedMobileCapabilities, trendMinWidth } from './mobile-management'

it('cached capabilities cannot restore pages removed from the current signed session scope', () => {
  const cached = { orders_view: true, reports_view: true, inventory_manage: true }
  expect(scopedMobileCapabilities(cached, ['inventory:read', 'inventory:write']))
    .toEqual({ orders_view: false, reports_view: false, inventory_manage: true, catalog_manage: false })
  expect(scopedMobileCapabilities(cached, [])).toEqual({ orders_view: false, reports_view: false, inventory_manage: false, catalog_manage: false })
  expect(scopedMobileCapabilities(cached, ['inventory:read']).inventory_manage).toBe(false)
  expect(scopedMobileCapabilities(undefined, ['catalog:read','catalog:write']).catalog_manage).toBe(true)
})

describe('mobile management navigation', () => {
  it('inventory-only accounts never show ordering and absent capabilities fail closed', () => {
    expect(availableMobileTabs({ orders_view: false, reports_view: false, inventory_manage: true })).toEqual(['inventory'])
    expect(availableMobileTabs(undefined)).toEqual([])
  })
  it('keeps management tabs hidden without server capabilities', () => {
    expect(availableMobileTabs({ orders_view: true, reports: false, inventory_add: false })).toEqual(['orders'])
    expect(availableMobileTabs(undefined)).toEqual([])
  })

  it('shows report and inventory tabs only when both capabilities are granted', () => {
    expect(availableMobileTabs({ orders_view: true, reports: true, inventory_add: true })).toEqual([
      'orders',
      'reports',
      'inventory',
    ])
  })

  it('prefers explicit capabilities while keeping one-release legacy fallback', () => {
    expect(availableMobileTabs({ orders_view: true, reports_view: true, inventory_manage: true })).toEqual([
      'orders',
      'reports',
      'inventory',
    ])
    expect(availableMobileTabs({ orders_view: true, reports: true, inventory_add: false })).toEqual(['orders', 'reports'])
    expect(availableMobileTabs({
      orders_view: true,
      reports_view: false,
      reports: true,
      inventory_manage: false,
      inventory_add: true,
    })).toEqual(['orders'])
  })
})

describe('mobile report date ranges', () => {
  it('creates an inclusive seven-day range ending after the selected day', () => {
    expect(reportRange(7, new Date('2026-09-20T15:30:00'))).toEqual({
      start: new Date(2026,8,14).toISOString(),
      end: new Date(2026,8,21).toISOString(),
    })
  })
})

describe('mobile report trend sizing', () => {
  it('fits short ranges to the phone width without a horizontal scrollbar', () => {
    expect(trendMinWidth(1)).toBe('100%')
    expect(trendMinWidth(7)).toBe('100%')
    expect(trendMinWidth(30)).toBe('1140px')
  })
})

describe('mobile report cards', () => {
  it('shows the four accounting metrics with stored and pass breakdown', () => {
    const cards = mobileReportCards({
      settlement_count: 2,
      operating_revenue: '200.00',
      stored_value_recharge: '100.00',
      pass_card_sales: '300.00',
      member_recharge: '400.00',
      actual_cash_inflow: '550.00',
      stored_value_consumed: '50.00',
      cashflow_totals: {},
    })
    expect(cards.map((row) => row.label)).toEqual(['营业消费金额', '会员充值收款', '实际现金流入', '储值余额核销'])
    expect(cards[1].subtitle).toContain('储值 ¥100.00')
    expect(cards[1].subtitle).toContain('次卡 ¥300.00')
  })
})
