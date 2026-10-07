import { expect, test } from 'vitest'
import {
  changeProductQuantity,
  clampOrderQuantities,
  selectionTotals,
  selectedOrderRows,
  switchVisitSelection,
  toggleServiceQuantity,
} from './order-selection'
import type { MobileCatalogItem } from './types'

test('service toggles between zero and one', () => {
  expect(toggleServiceQuantity({}, 'service-1')).toEqual({ 'service-1': 1 })
  expect(toggleServiceQuantity({ 'service-1': 1 }, 'service-1')).toEqual({ 'service-1': 0 })
})

test('manual sales quantity is independent from old catalog stock', () => {
  const item = { id: 'product-1', stock_tracked: true, stock_quantity: '2' }
  expect(changeProductQuantity({ 'product-1': 2 }, item, 1)).toEqual({ 'product-1': 3 })
})

test('product quantity cannot become negative', () => {
  const item = { id: 'product-1', stock_tracked: false, stock_quantity: '0' }
  expect(changeProductQuantity({}, item, -1)).toEqual({ 'product-1': 0 })
})

test('selected rows contain only positive quantities', () => {
  const catalog = [
    { id: 'service-1', name: '搓澡', price: '30.00' },
    { id: 'product-1', name: '牛奶', price: '5.00' },
  ] as MobileCatalogItem[]

  expect(selectedOrderRows(catalog, { 'service-1': 1, 'product-1': 0 }))
    .toEqual([{ ...catalog[0], quantity: 1 }])
})

test('refresh removes inactive sales but preserves manual sales quantity independently of stock', () => {
  const catalog = [
    { id: 'service-1', kind: 'service', stock_tracked: false, stock_quantity: '0' },
    { id: 'product-1', kind: 'product', stock_tracked: true, stock_quantity: '2' },
  ] as MobileCatalogItem[]

  expect(clampOrderQuantities(catalog, {
    'service-1': 3,
    'product-1': 5,
    removed: 4,
  })).toEqual({ 'service-1': 1, 'product-1': 5 })
})

test('summary distinguishes selected kinds from total product units', () => {
  expect(selectionTotals([
    { price: '30.00', quantity: 1 },
    { price: '5.00', quantity: 3 },
  ])).toEqual({ kinds: 2, units: 4, amount: 45 })
})

test('switching visits clears the current selection', () => {
  expect(switchVisitSelection('visit-1', 'visit-2', { drink: 3 })).toEqual({
    changed: true,
    visitId: 'visit-2',
    quantities: {},
  })
  expect(switchVisitSelection('visit-2', 'visit-2', { drink: 3 })).toEqual({
    changed: false,
    visitId: 'visit-2',
    quantities: { drink: 3 },
  })
})
