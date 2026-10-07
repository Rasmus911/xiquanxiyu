import { expect, it } from 'vitest'
import { VisitDraftBook } from './visit-drafts'

it('capture belongs to its visit and cannot change with later edits', () => {
  const drafts = new VisitDraftBook()
  const input = { soap: 2 }
  drafts.replace('a', input); input.soap = 7
  const target = drafts.capture('a', 3)
  drafts.replace('b', { water: 3 }); drafts.replace('a', { soap: 9 })
  expect(target).toEqual({ visitId: 'a', visitVersion: 3, quantities: { soap: 2 }, units: 2, kinds: 1 })
  expect(Object.isFrozen(target.quantities)).toBe(true)
  drafts.clear('a')
  expect(drafts.read('b')).toEqual({ water: 3 })
  const read = drafts.read('b'); read.water = 99
  expect(drafts.read('b')).toEqual({ water: 3 })
})
