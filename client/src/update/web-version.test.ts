import { describe, expect, it } from 'vitest'
import { webUpdateDecision } from './web-version'

const remote = { buildId: '20260927.2', required: false }

describe('webUpdateDecision', () => {
  it('does nothing for the current build', () => {
    expect(webUpdateDecision('20260927.2', remote, null)).toBe('none')
  })

  it('offers a safe refresh for a different build', () => {
    expect(webUpdateDecision('20260927.1', remote, null)).toBe('ready')
  })

  it('defers refresh while a business write is active', () => {
    expect(webUpdateDecision('20260927.1', remote, '正在确认收款')).toBe('deferred')
  })

  it('defers a required refresh until the write ends', () => {
    const required = { ...remote, required: true }
    expect(webUpdateDecision('20260927.1', required, '正在确认收款')).toBe('deferred')
    expect(webUpdateDecision('20260927.1', required, null)).toBe('required')
  })
})
