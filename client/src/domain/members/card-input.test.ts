import { expect, it } from 'vitest'
import { normalizeCardInput } from './card-input'

it.each([
  ['000315346091\r\n', '000315346091'], ['315346091', '315346091'], ['0', '0'],
  ['9'.repeat(64), '9'.repeat(64)], ['9'.repeat(65), null], ['', null],
  ['31 5346091', null], ['３15346091', null], ['123\n456', null], [' 123', null],
])('normalizes local card text %j to %j', (input, expected) => {
  expect(normalizeCardInput(input)).toBe(expected)
})
