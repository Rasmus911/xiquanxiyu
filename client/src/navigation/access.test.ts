import { expect, it } from 'vitest'
import { assertSessionUi, landingPath, pageAllowed } from './access'
import { menuGroupsForPages } from './menu'

it('cashier can reach receipt reprint and payment but never reports', () => {
  const pages = ['wristbands', 'members', 'print-jobs']
  const caps = { checkout_write: true, member_write: true, receipt_reprint: true }
  expect(menuGroupsForPages(pages, caps).flatMap(group => group.items.map(item => item.path))).toEqual(['/', '/members', '/print-jobs'])
  expect(pageAllowed(pages, '/print-jobs', caps)).toBe(true)
  expect(pageAllowed(pages, '/checkout', caps)).toBe(true)
  expect(pageAllowed(pages, '/reports', caps)).toBe(false)
  expect(pageAllowed(pages, '/members/member-1/recharge', caps)).toBe(true)
  expect(pageAllowed(pages, '/members/member-1/pass-purchase', caps)).toBe(true)
})
it('an ordering-only account cannot collect money or reach unknown paths', () => {
  expect(pageAllowed(['wristbands'], '/visits/guest-1', { visit_order: true })).toBe(true)
  expect(pageAllowed(['wristbands'], '/checkout', { checkout_write: false })).toBe(false)
  expect(pageAllowed(['wristbands'], '/checkout', {})).toBe(false)
  expect(pageAllowed(['wristbands'], '/something-private', { checkout_write: true })).toBe(false)
})
it('inventory lands on inventory and has no catalog page from its internal read scope', () => {
  expect(landingPath(['inventory'])).toBe('/inventory')
  expect(landingPath([])).toBe('/login')
  expect(pageAllowed(['inventory'], '/catalog', {})).toBe(false)
  expect(menuGroupsForPages(['inventory'], { inventory_write: true }).flatMap(group => group.items.map(item => item.path))).toEqual(['/inventory'])
})
it('server version without page grants cannot be interpreted as an administrator', () => {
  expect(() => assertSessionUi({})).toThrow(/更新|版本/)
  expect(() => assertSessionUi({ ui_pages: ['inventory'], capabilities: { inventory_write: 'yes' } })).toThrow()
  expect(() => assertSessionUi({ ui_pages: ['inventory'], capabilities: { inventory_write: true } })).not.toThrow()
})
