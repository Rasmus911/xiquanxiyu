import { expect, it } from 'vitest'
import { costPreview, warningPreview } from './receiving'

it('calculates costs in the selected receiving unit, not per bag', () => {
  expect(costPreview('4', '120', '200')).toEqual({ total: '480.00', baseUnit: '0.600000' })
  expect(costPreview('3', '0.10', '1')).toEqual({ total: '0.30', baseUnit: '0.100000' })
  expect(costPreview('0.125', '1.24', '1')).toEqual({ total: '0.16', baseUnit: '1.240000' })
})
it('does not turn unset or invalid costs into zero', () => {
  expect(costPreview('4', '', '200')).toBeNull()
  expect(costPreview('4', '-1', '200')).toBeNull()
  expect(costPreview('4', '1.234', '200')).toBeNull()
  expect(costPreview('4', '0', '200')?.total).toBe('0.00')
})
it('converts the receiving quantity before a fifteen percent warning', () => {
  expect(warningPreview('800.000')).toBe('120.000')
  expect(warningPreview('0.001')).toBe('0.001')
})
