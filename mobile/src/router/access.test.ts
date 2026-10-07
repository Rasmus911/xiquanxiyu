import { describe, expect, it } from 'vitest'
import { mobileLanding, routeAccess } from './access'

const ownerSession = { capabilities: { orders_view: true, reports_view: true, inventory_manage: true } }
const ordinarySession = { capabilities: { orders_view: true, reports_view: false, inventory_manage: false } }

it('inventory-only accounts land on inventory and cannot visit an ordering route', () => {
  const capabilities = { orders_view: false, reports_view: false, inventory_manage: true }
  expect(mobileLanding(capabilities)).toBe('/inventory')
  expect(routeAccess('orders', { capabilities })).toBe('forbidden')
  expect(routeAccess('visit-order', { capabilities })).toBe('forbidden')
  expect(routeAccess('login', { capabilities })).toBe('inventory')
  expect(routeAccess('profile', { capabilities })).toBe('allow')
  expect(mobileLanding({ orders_view: false, reports_view: false, inventory_manage: false })).toBe('/login')
})

describe('mobile route access', () => {
  it('requires login for business routes', () => {
    expect(routeAccess('orders', null)).toBe('login')
    expect(routeAccess('catalog', null)).toBe('login')
    expect(routeAccess('catalog', ordinarySession)).toBe('forbidden')
    expect(routeAccess('catalog', { capabilities: { catalog_manage: true } })).toBe('allow')
  })

  it('allows only explicit owner capabilities on management routes', () => {
    expect(routeAccess('reports', ownerSession)).toBe('allow')
    expect(routeAccess('reports', ordinarySession)).toBe('forbidden')
    expect(routeAccess('inventory', ordinarySession)).toBe('forbidden')
  })

  it('redirects an authenticated user away from login', () => {
    expect(routeAccess('login', ownerSession)).toBe('orders')
  })
})
