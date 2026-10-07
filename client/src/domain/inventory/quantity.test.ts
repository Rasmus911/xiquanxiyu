import { expect, it } from 'vitest'
import { previewStockQuantity } from './quantity'

it('converts fixed decimal quantities exactly without rounding', () => {
  expect(previewStockQuantity('4', 'package', '200')).toBe('800.000')
  expect(previewStockQuantity('0.1', 'package', '0.2')).toBe('0.020')
  expect(previewStockQuantity('999999999.999', 'base', '1')).toBe('999999999.999')
})

it.each([
  ['1.001', 'package', '1.001'],
  ['0.001', 'package', '0.001'],
  ['999999999.999', 'package', '1.001'],
  ['1000000000', 'base', '1'],
  ['1000000000.000', 'package', '1'],
  ['1.0001', 'base', '1'],
  ['', 'base', '1'],
  ['NaN', 'base', '1'],
  ['Infinity', 'base', '1'],
  ['1e3', 'base', '1'],
  ['-1', 'base', '1'],
  ['0', 'base', '1'],
  ['1', 'package', '0'],
  ['1', 'package', '-1'],
  ['1', 'package', '1.0001'],
  ['1', 'package', 'Infinity'],
  ['1', 'unknown', '1'],
])('does not advertise a valid balance for quantity=%s unit=%s factor=%s', (quantity, unit, factor) => {
  expect(previewStockQuantity(quantity, unit, factor)).toBe('—')
})

it('supports signed adjustment deltas and explicit zero opening without weakening factor validation', () => {
  expect(previewStockQuantity('-0.125', 'package', '200', { signed: true })).toBe('-25.000')
  expect(previewStockQuantity('-1000000000', 'base', '1', { signed: true })).toBe('—')
  expect(previewStockQuantity('0.000', 'package', '200', { zero: true })).toBe('0.000')
  expect(previewStockQuantity('0', 'package', '0', { zero: true })).toBe('—')
})
