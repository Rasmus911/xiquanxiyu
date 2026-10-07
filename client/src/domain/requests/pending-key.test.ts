import { beforeEach, describe, expect, it } from 'vitest'
import { clearPendingRequestKey, pendingRequestKey } from './pending-key'

describe('pending request key', () => {
  beforeEach(() => sessionStorage.clear())

  it('reuses the same key for an unchanged request until success', () => {
    const first = pendingRequestKey('visit:v1:add', 'v1|p1:2')
    expect(pendingRequestKey('visit:v1:add', 'v1|p1:2')).toBe(first)
    clearPendingRequestKey('visit:v1:add')
    expect(pendingRequestKey('visit:v1:add', 'v1|p1:2')).not.toBe(first)
  })

  it('rotates the key when the visit or quantities change', () => {
    const first = pendingRequestKey('visit:v1:add', 'v1|p1:1')
    expect(pendingRequestKey('visit:v1:add', 'v1|p1:2')).not.toBe(first)
  })

  it('an older completion cannot clear a newer request for the same visit', () => {
    const old = pendingRequestKey('visit:v1:ticket', 'adult')
    const current = pendingRequestKey('visit:v1:ticket', 'child')
    clearPendingRequestKey('visit:v1:ticket', old)
    expect(pendingRequestKey('visit:v1:ticket', 'child')).toBe(current)
    clearPendingRequestKey('visit:v1:ticket', current)
    expect(pendingRequestKey('visit:v1:ticket', 'child')).not.toBe(current)
  })
})
