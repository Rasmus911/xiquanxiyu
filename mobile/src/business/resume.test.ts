// @vitest-environment jsdom
import { afterEach, expect, test, vi } from 'vitest'
import { createApp, type App } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import Root from '../App.vue'
import { http } from '../api'
import { acceptBusinessState, clearBusinessSession } from './state'
import { getAccessToken, setSession } from '../session'
const native = vi.hoisted(() => ({ resume: null as null | (() => Promise<void>) }))
vi.mock('../native', () => ({ getInstalledBuildNumber: async () => 8, isNativeAndroidApp: () => false, isNativeApp: () => false, onAppResume: async (callback: () => Promise<void>) => { native.resume = callback; return async () => undefined } }))
let app: App; let host: HTMLDivElement
afterEach(() => { app?.unmount(); host?.remove(); vi.unstubAllGlobals() })
test('native resume reconciles missed reset before another bootstrap can refill cache', async () => {
  vi.stubGlobal('fetch', async () => ({ ok: true, json: async () => ({ schemaVersion: 1, android: null }) }))
  setActivePinia(createPinia()); clearBusinessSession()
  const state = { period_id: 'p1', policy_version: 1, business_revision: 1, maintenance: false, owner_reset_allowed: false }
  acceptBusinessState(state, ['mobile:order']); setSession({ access_token: 'access', refresh_token: 'refresh' })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/orders', name: 'orders', component: { template: '<div />' } }, { path: '/login', name: 'login', component: { template: '<div />' } }] })
  await router.push('/orders'); await router.isReady()
  app = createApp(Root); app.use(setActivePinia(createPinia())); app.use(router)
  host = document.createElement('div'); document.body.append(host); app.mount(host)
  await new Promise(resolve => setTimeout(resolve, 0))
  const paths: string[] = []
  http.defaults.adapter = async config => { paths.push(String(config.url)); return { config, headers: {}, status: 200, statusText: '', data: { data: { ...state, period_id: 'p2' } } } }
  expect(native.resume).toBeTypeOf('function')
  await native.resume!()
  expect(paths).toEqual(['/business/state'])
  expect(getAccessToken()).toBe('')
})
test('a resume callback waiting on update policy cannot refresh a replacement login', async () => {
  vi.stubGlobal('fetch', async () => ({ ok: true, json: async () => ({ schemaVersion: 1, android: null }) }))
  const pinia = createPinia(); setActivePinia(pinia); clearBusinessSession()
  const state = { period_id: 'p1', policy_version: 1, business_revision: 1, maintenance: false, owner_reset_allowed: false }
  acceptBusinessState(state, ['mobile:order']); setSession({ access_token: 'access', refresh_token: 'refresh' })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/login', name: 'login', component: { template: '<div />' } }] })
  await router.push('/login'); await router.isReady()
  app = createApp(Root); app.use(pinia); app.use(router)
  host = document.createElement('div'); document.body.append(host); app.mount(host)
  await new Promise(resolve => setTimeout(resolve, 0))
  let release!: () => void
  vi.stubGlobal('fetch', () => new Promise(resolve => { release = () => resolve({ ok: true, json: async () => ({ schemaVersion: 1, android: null }) }) }))
  const paths: string[] = []
  http.defaults.adapter = async config => { paths.push(String(config.url)); return { config, headers: {}, status: 200, statusText: '', data: { data: state } } }
  const resume = native.resume!()
  clearBusinessSession(); acceptBusinessState(state, ['mobile:order']); setSession({ access_token: 'new', refresh_token: 'new-refresh' })
  const { useSessionStore } = await import('../stores/session')
  useSessionStore().authenticated = true
  release(); await resume
  expect(paths).toEqual([])
  expect(getAccessToken()).toBe('new')
})
