import { expect, it } from 'vitest'
import { moveBefore } from './layout'

it('moves an item without mutating the original or accepting unknown IDs', () => {
  const ids = ['scrub', 'towel', 'mud']
  expect(moveBefore(ids, 'mud', 'towel')).toEqual(['scrub', 'mud', 'towel'])
  expect(ids).toEqual(['scrub', 'towel', 'mud'])
  expect(moveBefore(ids, 'missing', 'towel')).toEqual(ids)
  expect(moveBefore(ids, 'towel', 'towel')).toEqual(ids)
})
