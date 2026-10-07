import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { getAccessToken, setAccessToken } from '../auth/session'
import { acceptBusinessState, clearBusinessSession } from '../business/state'
import { http } from '../api/http'
import { startRealtime, stopRealtime } from './useRealtime'
const sockets = vi.hoisted(() => [] as Array<{ handlers: Record<string, (...args: any[]) => any>; on: any; onAny: any; disconnect: any }>)
vi.mock('socket.io-client', () => ({ io: () => { const s = { handlers: {} as Record<string, (...args: any[]) => any>, on(name: string, handler: (...args: any[]) => any) { this.handlers[name] = handler }, onAny(handler: (...args: any[]) => any) { this.handlers.any = handler }, disconnect() {} }; sockets.push(s); return s } }))
const state = { period_id: 'p1', policy_version: 1, business_revision: 1, maintenance: false, owner_reset_allowed: true }
beforeEach(() => { setActivePinia(createPinia()); clearBusinessSession(); acceptBusinessState(state, ['*']); setAccessToken('session') })
afterEach(() => stopRealtime())
test('a focus check completing after its socket stopped cannot dispatch a refresh', async () => {
  let release!: () => void
  http.defaults.adapter = config => new Promise(resolve => { release = () => resolve({ config, headers: {}, status: 200, statusText: '', data: { data: state } }) })
  const refresh = vi.fn()
  window.addEventListener('xiquan:realtime', refresh)
  try {
    startRealtime(); window.dispatchEvent(new Event('focus'))
    await Promise.resolve()
    stopRealtime(); release()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(refresh).not.toHaveBeenCalled()
  } finally { window.removeEventListener('xiquan:realtime', refresh) }
})
test('socket reset immediately invalidates token and old socket callbacks cannot touch replacement session', () => {
  startRealtime()
  const old = sockets.at(-1)!
  old.handlers.any!('business.reset', { period_id: 'p2', policy_version: 1, reset_id: 't1' })
  expect(getAccessToken()).toBe('')
  acceptBusinessState({ ...state, period_id: 'p2' }, ['*']); setAccessToken('new')
  old.handlers.any!('business.reset', { period_id: 'p3', policy_version: 1, reset_id: 't2' })
  expect(getAccessToken()).toBe('new')
})
test('focus reconciles missed changes before allowing cached business data', async () => {
  http.defaults.adapter = async config => ({ config, headers: {}, status: 200, statusText: '', data: { data: { ...state, period_id: 'p2' } } })
  startRealtime(); window.dispatchEvent(new Event('focus'))
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(getAccessToken()).toBe('')
})
