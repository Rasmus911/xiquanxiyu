import { describe, expect, it } from 'vitest'
import { memberCardKinds, memberPrimaryValue } from './presentation'

describe('member card presentation', () => {
  it('keeps stored value and pass cards visually distinct', () => {
    expect(memberCardKinds({ has_stored_value: true, has_pass: false })).toEqual(['stored'])
    expect(memberCardKinds({ has_stored_value: false, has_pass: true })).toEqual(['pass'])
    expect(memberCardKinds({ has_stored_value: true, has_pass: true })).toEqual(['stored', 'pass'])
    expect(memberCardKinds({ has_stored_value: false, has_pass: false })).toEqual(['none'])
  })

  it('shows balance for stored cards and remaining visits for pass cards', () => {
    expect(memberPrimaryValue({ has_stored_value: true, balance: '188.00' })).toBe('¥188.00')
    expect(memberPrimaryValue({ has_pass: true, pass_remaining: 8, pass_total: 10 })).toBe('8 / 10 次')
  })
})
