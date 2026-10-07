import { beforeEach, expect, test } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { http } from '../api/http'
import { useAuthStore } from './auth'
import { businessState, clearBusinessSession, permissions } from '../business/state'
import { getAccessToken } from '../auth/session'
beforeEach(() => { clearBusinessSession(); setActivePinia(createPinia()) })
test('web login sends channel and uses authoritative state and scope', async () => {
  let body: any
  http.defaults.adapter = async config => {
    body = JSON.parse(config.data)
    return { config, headers: {}, status: 200, statusText: '', data: { data: {
      access_token: 'access', refresh_token: 'refresh', employee: { id: 'owner', role: 'cashier' }, terminal: { id: 't1' },
      business_state: { period_id: 'p1', business_revision: 3, policy_version: 2, maintenance: false, owner_reset_allowed: true,
        ui_pages: ['wristbands'], capabilities: { checkout_write: true } }, permissions: ['*'],
    } } }
  }
  await useAuthStore().login('user', 'password', 'DESK')
  expect(body.client_channel).toBe('web')
  expect(businessState.value?.owner_reset_allowed).toBe(true)
  expect(permissions.value).toEqual(['*'])
  expect(getAccessToken()).toBe('access')
})

test('login rejects an old backend response without UI grants before accepting a token', async () => {
  http.defaults.adapter = async config => ({ config, headers: {}, status: 200, statusText: '', data: { data: {
    access_token: 'unsafe', refresh_token: 'refresh', employee: { id: 'old' }, terminal: { id: 't1' },
    business_state: { period_id: 'p1', business_revision: 0, policy_version: 1, maintenance: false, owner_reset_allowed: false }, permissions: ['*'],
  } } })
  await expect(useAuthStore().login('old', 'fixture-only', 'TEST')).rejects.toThrow(/更新|版本/)
  expect(getAccessToken()).toBe('')
})
test('clear removes employee immediately and a delayed login cannot refill it', async () => {
  let finish!: () => void
  http.defaults.adapter = config => new Promise(resolve => { finish = () => resolve({ config, headers: {}, status: 200, statusText: '', data: { data: { access_token: 'old', employee: { id: 'old' } } } }) })
  const store = useAuthStore()
  const pending = store.login('old', 'password', 'DESK')
  await Promise.resolve(); await Promise.resolve()
  clearBusinessSession(); finish()
  await expect(pending).rejects.toBeInstanceOf(Error)
  expect(store.employee).toBeNull()
  expect(getAccessToken()).toBe('')
})
