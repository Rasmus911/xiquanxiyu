import { describe, expect, it } from 'vitest'
import { beginBatch, cancelBatch, finishBatch, toggleSelected, type WristbandSelectionState } from './selection'

const empty: WristbandSelectionState = { active: false, selectedIds: [] }

describe('wristband batch selection', () => {
  it('does not select cards outside explicit batch mode', () => {
    expect(toggleSelected(empty, 'w1')).toEqual(empty)
  })

  it('starts batch mode and toggles unique wristbands', () => {
    const started = beginBatch(empty)
    expect(toggleSelected(started, 'w1').selectedIds).toEqual(['w1'])
    expect(toggleSelected(toggleSelected(started, 'w1'), 'w1').selectedIds).toEqual([])
  })

  it('clears and exits after cancel or successful action', () => {
    const selected = { active: true, selectedIds: ['w1', 'w2'] }
    expect(cancelBatch(selected)).toEqual(empty)
    expect(finishBatch(selected)).toEqual(empty)
  })
})
