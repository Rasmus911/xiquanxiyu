// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import axios from 'axios'
import { getAccessToken, setSession } from '../session'
import { acceptBusinessState, clearBusinessSession } from '../business/state'
import { http, refreshAccessToken } from '../api'
import { useBusinessStore } from '../stores/business'
import { useConnectivityStore } from '../stores/connectivity'
import { connectRealtime, disconnectRealtime } from './useRealtime'
const sockets = vi.hoisted(() => [] as Array<{ handlers: Record<string, (...args: any[]) => any>; on: any; disconnect: any }>)
vi.mock('socket.io-client', () => ({ io: () => { const s = { handlers: {} as Record<string, (...args: any[]) => any>, on(name: string, handler: (...args: any[]) => any) { this.handlers[name] = handler }, disconnect() {} }; sockets.push(s); return s } }))
const state = { period_id: 'p1', policy_version: 1, business_revision: 1, maintenance: false, owner_reset_allowed: false }
beforeEach(() => { setActivePinia(createPinia()); clearBusinessSession(); acceptBusinessState(state, ['mobile:order']); setSession({ access_token: 'session', refresh_token: 'refresh' }) })
afterEach(() => disconnectRealtime())
test('a focus check completing after disconnect cannot schedule another bootstrap', async () => {
  const paths: string[] = []
  let release!: () => void
  http.defaults.adapter = config => {
    paths.push(String(config.url))
    return new Promise(resolve => { release = () => resolve({ config, headers: {}, status: 200, statusText: '', data: { data: state } }) })
  }
  connectRealtime(); window.dispatchEvent(new Event('focus'))
  await Promise.resolve()
  disconnectRealtime(); release()
  await new Promise(resolve => setTimeout(resolve, 400))
  expect(paths).toEqual(['/business/state'])
})
test('mobile reset clears the real cart and token before another order', () => {
  const business = useBusinessStore(); business.quantities = { service: 2 }
  useConnectivityStore().markSynced()
  connectRealtime()
  const current = sockets.at(-1)!
  expect(current.handlers['business.reset']).toBeTypeOf('function')
  current.handlers['business.reset']!({ period_id: 'p2', policy_version: 1, reset_id: 't1' })
  expect(business.quantities).toEqual({})
  expect(getAccessToken()).toBe('')
  expect(useConnectivityStore().lastSyncAt).toBeNull()
})
test('mobile reconnect verifies state before requesting new domain data', async () => {
  const paths: string[] = []
  http.defaults.adapter = async config => { paths.push(String(config.url)); return { config, headers: {}, status: 200, statusText: '', data: { data: { ...state, period_id: 'p2' } } } }
  connectRealtime(); await sockets.at(-1)!.handlers.connect!()
  expect(paths).toEqual(['/business/state'])
  expect(getAccessToken()).toBe('')
})
test('an expired old socket cannot invalidate a session after its access token was refreshed', async () => {
  const original = axios.defaults.adapter
  axios.defaults.adapter = async config => ({ config, headers: {}, status: 200, statusText: '', data: { data: { access_token: 'refreshed', business_state: state, permissions: ['mobile:order'] } } })
  try {
    connectRealtime(); const old = sockets.at(-1)!
    await refreshAccessToken()
    old.handlers['session.invalidated']!({ reason: 'SESSION_REVOKED' })
    expect(getAccessToken()).toBe('refreshed')
  } finally { axios.defaults.adapter = original }
})
