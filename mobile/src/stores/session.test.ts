// @vitest-environment jsdom

import { beforeEach, expect, test, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { http } from '../api'
import { useSessionStore } from './session'
import { businessState, clearBusinessSession, permissions } from '../business/state'

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  clearBusinessSession()
  setActivePinia(createPinia())
  vi.restoreAllMocks()
})

test('logging in immediately unlocks protected routes and logging out locks them again', async () => {
  const session = useSessionStore()
  expect(session.authenticated).toBe(false)

  http.defaults.adapter = async config => {
    if (config.url === '/auth/login') expect(JSON.parse(config.data).client_channel).toBe('mobile')
    return { config, headers: {}, status: 200, statusText: '', data: { success: true, data: config.url === '/auth/login' ? { access_token: 'access', refresh_token: 'refresh', employee: { id: 'e1', username: 'worker', display_name: '员工', role: 'male_scrubber', role_label: '搓澡师', capabilities: { order_all: true, catalog_all: true, reports_view: true, inventory_manage: true, reports: true, inventory_add: true } }, business_state: { period_id: 'p1', business_revision: 1, policy_version: 1, maintenance: false, owner_reset_allowed: false }, permissions: ['mobile:order', 'report:read', 'inventory:read', 'inventory:write'] } : {} } }
  }

  await session.login('worker', 'password')
  expect(session.authenticated).toBe(true)
  expect(businessState.value?.period_id).toBe('p1')
  expect(permissions.value).toContain('report:read')

  session.logout()
  expect(session.authenticated).toBe(false)
})
