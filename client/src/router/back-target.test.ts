import { describe, expect, it } from 'vitest'
import { resolveBackTarget } from './back-target'

describe('resolveBackTarget', () => {
  it('prefers a safe explicit return target', () => {
    expect(resolveBackTarget({ query: { returnTo: '/visits/v1' }, meta: { parentRoute: '/' } })).toBe('/visits/v1')
  })

  it('uses route parent metadata when no explicit target exists', () => {
    expect(resolveBackTarget({ query: {}, meta: { parentRoute: '/members' } })).toBe('/members')
  })

  it('rejects protocol-relative and non-path return values', () => {
    expect(resolveBackTarget({ query: { returnTo: '//evil.example' }, meta: { parentRoute: '/members' } })).toBe('/members')
    expect(resolveBackTarget({ query: { returnTo: 'javascript:alert(1)' }, meta: {} }, '/')).toBe('/')
  })
})
