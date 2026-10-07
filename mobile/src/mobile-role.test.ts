import { expect, test } from 'vitest'
import { canFilterBathAreas, isAllowedMobileRole } from './mobile-role'

test('allows administrators to use mobile ordering', () => {
  expect(isAllowedMobileRole('admin')).toBe(true)
})

test('lets administrators filter both bath areas', () => {
  expect(canFilterBathAreas('admin')).toBe(true)
})

test('keeps unsupported desktop roles out of mobile ordering', () => {
  expect(isAllowedMobileRole('cashier')).toBe(false)
  expect(isAllowedMobileRole('manager')).toBe(false)
})

test('inventory role is supported without granting bath-area ordering', () => {
  expect(isAllowedMobileRole('inventory')).toBe(true)
  expect(canFilterBathAreas('inventory')).toBe(false)
})
