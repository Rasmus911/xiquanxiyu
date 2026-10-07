import { describe, expect, it } from 'vitest'
import { formatBusinessTime } from './business-time'

describe('business time presentation', () => {
  it('uses readable China business time instead of raw UTC strings', () => {
    expect(formatBusinessTime('2026-09-30T12:04:14.591959+00:00')).toBe('2026-09-30 20:04:14')
  })
  it('handles empty or invalid values', () => {
    for (const value of [undefined, null, '', 'not-a-time']) expect(formatBusinessTime(value)).toBe('—')
  })
})
