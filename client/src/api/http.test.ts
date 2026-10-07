import { describe, expect, it } from 'vitest'
import { AxiosError } from 'axios'
import { apiData, http, reconcileBusinessSession } from './http'
import { acceptBusinessState, businessState, clearBusinessSession } from '../business/state'
import { getAccessToken, setAccessToken } from '../auth/session'

it.each(['PERMISSION_DENIED', 'PROTECTED_ACCOUNT', 'OWNER_REQUIRED'])('action denial %s preserves the operator session', async code => {
  clearBusinessSession(); setAccessToken('current')
  http.defaults.adapter = async config => { throw new AxiosError('action denied', '', config, undefined,
    { config, headers: {}, status: 403, statusText: '', data: { success: false, error: { code } } }) }
  await expect(http.patch('/employees/target', { is_active: true })).rejects.toBeInstanceOf(Error)
  expect(getAccessToken()).toBe('current')
})
it.each([[401, 'SESSION_REVOKED'], [403, 'CHANNEL_FORBIDDEN']])('real session denial %s %s clears the session', async (status, code) => {
  clearBusinessSession(); setAccessToken('current')
  http.defaults.adapter = async config => { throw new AxiosError('session denied', '', config, undefined,
    { config, headers: {}, status: Number(status), statusText: '', data: { success: false, error: { code } } }) }
  await expect(http.get('/business/state')).rejects.toBeInstanceOf(Error)
  expect(getAccessToken()).toBe('')
})

describe('apiData', () => {
  it('extracts the standard API payload', () => {
    expect(apiData({ data: { data: { ok: true } } })).toEqual({ ok: true })
  })
})
it('reconciliation clears stale cached state on a missed policy change', async () => {
  acceptBusinessState({ period_id: 'p1', business_revision: 1, policy_version: 1, maintenance: false, owner_reset_allowed: true }, ['*'])
  setAccessToken('current')
  http.defaults.adapter = async config => ({ config, headers: {}, status: 200, statusText: '', data: { data: { period_id: 'p1', business_revision: 1, policy_version: 2, maintenance: false, owner_reset_allowed: false } } })
  expect(await reconcileBusinessSession()).toBe(false)
  expect(businessState.value).toBeNull()
  expect(getAccessToken()).toBe('')
})
it.each([200, 401])('isolates delayed old HTTP %s from replacement login', async (status) => {
  let finish!: () => void
  http.defaults.adapter = config => new Promise((resolve, reject) => {
    finish = () => {
      const response = { config, status, statusText: '', headers: {}, data: { data: { old: true } } }
      if (status === 401) reject(new AxiosError('old denied', '', config, undefined, response))
      else resolve(response)
    }
  })
  setAccessToken('old')
  const old = http.get('/members')
  await Promise.resolve(); await Promise.resolve()
  clearBusinessSession()
  setAccessToken('new')
  finish()
  await expect(old).rejects.toBeInstanceOf(Error)
  expect(getAccessToken()).toBe('new')
})
it('a request queued before invalidation cannot borrow the next login token', async () => {
  let used = ''
  http.defaults.adapter = async config => { used = String(config.headers.Authorization); return { config, headers: {}, status: 200, statusText: '', data: { data: {} } } }
  setAccessToken('old')
  const pending = http.get('/members')
  clearBusinessSession(); setAccessToken('new')
  await expect(pending).rejects.toBeInstanceOf(Error)
  expect(used).not.toBe('Bearer new')
})

