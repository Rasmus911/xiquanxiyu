import { expect, test } from 'vitest'
import { decideUpdate } from './versioning'

const config = { version: '1.1.0', versionCode: 11, minimumVersionCode: 10 }

test('requires update below minimum build', () => {
  expect(decideUpdate(9, config)).toBe('required')
})

test('offers an update below the latest build', () => {
  expect(decideUpdate(10, config)).toBe('optional')
})

test('does not prompt the current build', () => {
  expect(decideUpdate(11, config)).toBe('none')
})

test('does not downgrade a newer build', () => {
  expect(decideUpdate(12, config)).toBe('none')
})
