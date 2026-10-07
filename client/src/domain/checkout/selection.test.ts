import { describe, expect, it } from 'vitest'
import { initialCheckoutSelection, toggleCheckoutVisit } from './selection'

const visits = [{ visit_id: 'v1' }, { visit_id: 'v2' }, { visit_id: 'v3' }]

describe('checkout visit selection', () => {
  it('preselects a party or only the current visit according to entry intent', () => {
    expect(initialCheckoutSelection(visits, 'v2', 'party')).toEqual(['v1', 'v2', 'v3'])
    expect(initialCheckoutSelection(visits, 'v2', 'selected')).toEqual(['v2'])
  })

  it('never allows the final selected visit to be removed', () => {
    expect(toggleCheckoutVisit(['v1'], 'v1')).toEqual(['v1'])
    expect(toggleCheckoutVisit(['v1', 'v2'], 'v1')).toEqual(['v2'])
  })
})
