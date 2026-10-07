// @vitest-environment jsdom

import { beforeEach, expect, test, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { http } from './api'
import { loginAndLoad } from './login-flow'
import { useBusinessStore } from './stores/business'
import { useSessionStore } from './stores/session'
import { acceptBusinessState, clearBusinessSession } from './business/state'
import { getAccessToken, setSession } from './session'

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  setActivePinia(createPinia())
  vi.restoreAllMocks()
})
test('a session change at login completion cannot bootstrap using the replacement credentials', async () => {
  const state = { period_id: 'p1', business_revision: 1, policy_version: 1, maintenance: false, owner_reset_allowed: false }
  const paths: string[] = []
  http.defaults.adapter = async config => {
    paths.push(String(config.url))
    return { config, headers: {}, status: 200, statusText: '', data: { data: config.url === '/auth/login' ? { access_token: 'old', refresh_token: 'old-refresh', employee: { id: 'e1', username: 'worker' }, business_state: state, permissions: ['mobile:order'] } : {} } }
  }
  const session = useSessionStore()
  session.$onAction(({ name, after }) => {
    if (name === 'login') after(() => {
      clearBusinessSession(); acceptBusinessState(state, ['mobile:order']); setSession({ access_token: 'new', refresh_token: 'new-refresh' }); session.authenticated = true
    })
  })
  await expect(loginAndLoad(session, useBusinessStore(), 'worker', 'secret')).rejects.toBeInstanceOf(Error)
  expect(paths).not.toContain('/mobile/bootstrap')
  expect(getAccessToken()).toBe('new')
})

test('a bootstrap failure clears the half-login and propagates its error', async () => {
  http.defaults.adapter = async config => {
    if (config.url === '/mobile/bootstrap') throw new Error('Network Error')
    return { config, headers: {}, status: 200, statusText: '', data: { data: config.url === '/auth/login' ? {
      access_token: 'access', refresh_token: 'refresh', employee: { id: 'e1', username: 'worker', capabilities: { order_all: true } },
      business_state: { period_id: 'p1', business_revision: 1, policy_version: 1, maintenance: false, owner_reset_allowed: false }, permissions: ['mobile:order'],
    } : {} } }
  }
  const session = useSessionStore()
  const business = useBusinessStore()

  await expect(loginAndLoad(session, business, 'worker', 'password')).rejects.toThrow('Network Error')

  expect(session.authenticated).toBe(false)
  expect(session.employee).toBeNull()
  expect(business.catalog).toEqual([])
})
