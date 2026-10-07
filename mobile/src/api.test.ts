// @vitest-environment jsdom

import axios, { AxiosError, type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { errorMessage, http, refreshAccessToken, reconcileBusinessSession } from './api'
import { acceptBusinessState, businessState, clearBusinessSession, permissions } from './business/state'
import { getAccessToken, setSession } from './session'

function response(config: AxiosRequestConfig, status: number, data: unknown): AxiosResponse {
  return {
    config: config as AxiosResponse['config'],
    data,
    headers: {},
    status,
    statusText: String(status),
  }
}

beforeEach(() => {
  clearBusinessSession()
  localStorage.clear()
  setSession({ access_token: 'access-1', refresh_token: 'refresh-1' })
})

afterEach(() => {
  vi.restoreAllMocks()
  axios.defaults.adapter = originalAdapter
})
const originalAdapter = axios.defaults.adapter

test.each([
  ['CHANNEL_FORBIDDEN', '入口'], ['ACCESS_POLICY_NOT_CONFIGURED', '策略'],
  ['TERMINAL_INVALID', '终端'], ['SESSION_REVOKED', '重新登录'],
])('mobile login error %s explains the next step', (code, expected) => {
  const config = {} as any
  const error = new AxiosError('Network Error', '', config, undefined,
    response(config, 403, { success: false, error: { code } }))
  expect(errorMessage(error)).toContain(expected)
})

test.each(['PERMISSION_DENIED', 'PROTECTED_ACCOUNT', 'OWNER_REQUIRED'])('action denial %s preserves mobile login', async code => {
  http.defaults.adapter = async config => { throw new AxiosError('action denied', '', config, undefined,
    response(config, 403, { success: false, error: { code } })) }
  await expect(http.post('/mobile/orders', {})).rejects.toBeInstanceOf(Error)
  expect(getAccessToken()).toBe('access-1')
})
test.each(['SESSION_REVOKED', 'ACCOUNT_DISABLED', 'TERMINAL_DISABLED'])('real session denial %s immediately clears without refresh', async code => {
  let refreshes = 0
  axios.defaults.adapter = async config => { refreshes++; return response(config, 200, { data: {} }) }
  http.defaults.adapter = async config => { throw new AxiosError('session denied', '', config, undefined,
    response(config, 401, { success: false, error: { code } })) }
  await expect(http.get('/mobile/bootstrap')).rejects.toBeInstanceOf(Error)
  expect(refreshes).toBe(0)
  expect(getAccessToken()).toBe('')
})

test('a 401 refreshes once and retries with the new access token', async () => {
  const requests: Array<{ url: string; authorization: string }> = []
  let businessAttempts = 0
  http.defaults.adapter = async (config) => {
    requests.push({
      url: String(config.url),
      authorization: String(config.headers?.Authorization || ''),
    })
    businessAttempts += 1
    if (businessAttempts === 1) {
      const failed = response(config, 401, { message: '令牌过期' })
      throw new AxiosError('Request failed with status code 401', 'ERR_BAD_REQUEST', config, undefined, failed)
    }
    return response(config, 200, { success: true, data: { wristbands: [] } })
  }
  let refreshes = 0
  axios.defaults.adapter = async config => {
    refreshes++
    expect(config.url).toMatch(/\/auth\/refresh$/)
    expect(config.headers.Authorization).toBe('Bearer refresh-1')
    return response(config, 200, { data: { access_token: 'access-2', business_state: { period_id: 'p1', business_revision: 1, policy_version: 1, maintenance: false, owner_reset_allowed: false }, permissions: ['mobile:order'] } })
  }

  const result = await http.get('/mobile/bootstrap')

  expect(result.status).toBe(200)
  expect(refreshes).toBe(1)
  expect(requests).toEqual([
    { url: '/mobile/bootstrap', authorization: 'Bearer access-1' },
    { url: '/mobile/bootstrap', authorization: 'Bearer access-2' },
  ])
  expect(getAccessToken()).toBe('access-2')
})

test('a failed refresh clears the session and announces logout', async () => {
  http.defaults.adapter = async (config) => {
    const failed = response(config, 401, { message: '登录状态已失效' })
    throw new AxiosError('Request failed with status code 401', 'ERR_BAD_REQUEST', config, undefined, failed)
  }
  axios.defaults.adapter = async config => { throw new AxiosError('refresh failed', '', config) }
  const loggedOut = vi.fn()
  window.addEventListener('xiquan:logged-out', loggedOut, { once: true })

  await expect(http.get('/mobile/bootstrap')).rejects.toBeInstanceOf(Error)

  expect(getAccessToken()).toBe('')
  expect(loggedOut).toHaveBeenCalledTimes(1)
})
test.each(['resolve', 'reject'])('an old refresh %s cannot replace or clear a new session', async outcome => {
  let finish!: () => void
  axios.defaults.adapter = config => new Promise((resolve, reject) => {
    finish = () => outcome === 'resolve'
      ? resolve(response(config, 200, { data: { access_token: 'obsolete' } }))
      : reject(new Error('old refresh failed'))
  })
  const old = refreshAccessToken()
  clearBusinessSession()
  setSession({ access_token: 'new-session', refresh_token: 'new-refresh' })
  finish()
  await expect(old).rejects.toBeInstanceOf(Error)
  expect(getAccessToken()).toBe('new-session')
})
test('an old refresh finalizer does not release a replacement refresh promise', async () => {
  const releases: Array<() => void> = []
  axios.defaults.adapter = config => new Promise(resolve => {
    const token = releases.length ? 'new-access' : 'old-access'
    releases.push(() => resolve(response(config, 200, { data: { access_token: token, business_state: { period_id: 'p1', business_revision: 1, policy_version: 1, maintenance: false, owner_reset_allowed: false }, permissions: ['mobile:order'] } })))
  })
  const old = refreshAccessToken().catch(() => undefined)
  clearBusinessSession()
  setSession({ access_token: 'new-session', refresh_token: 'new-refresh' })
  const current = refreshAccessToken()
  releases[0]!()
  await old
  const concurrent = refreshAccessToken()
  expect(releases).toHaveLength(2)
  releases[1]!()
  await Promise.all([current, concurrent])
  expect(getAccessToken()).toBe('new-access')
})
test('refresh applies server scope and business period and transport carries its period', async () => {
  const state = { period_id: 'p-new', business_revision: 4, policy_version: 3, maintenance: false, owner_reset_allowed: false }
  axios.defaults.adapter = async config => response(config, 200, { data: { access_token: 'fresh', business_state: state, permissions: ['mobile:order'] } })
  await refreshAccessToken()
  expect(businessState.value?.period_id).toBe('p-new')
  expect(permissions.value).toEqual(['mobile:order'])
  http.defaults.adapter = async config => {
    expect(config.headers['X-Business-Period']).toBe('p-new')
    return response(config, 200, { data: {} })
  }
  await http.get('/mobile/bootstrap')
})
test('period change error clears session using actual nested server error code', async () => {
  acceptBusinessState({ period_id: 'p1', business_revision: 1, policy_version: 1, maintenance: false, owner_reset_allowed: false }, ['mobile:order'])
  http.defaults.adapter = async config => { throw new AxiosError('denied', '', config, undefined, response(config, 409, { success: false, message: '经营期已变化', error: { code: 'BUSINESS_PERIOD_CHANGED', details: {} } })) }
  await expect(http.get('/mobile/bootstrap')).rejects.toBeInstanceOf(Error)
  expect(getAccessToken()).toBe('')
  expect(businessState.value).toBeNull()
})
test('reconciliation clears old data when state is unavailable', async () => {
  acceptBusinessState({ period_id: 'p1', business_revision: 1, policy_version: 1, maintenance: false, owner_reset_allowed: false }, ['mobile:order'])
  http.defaults.adapter = async () => { throw new Error('offline') }
  expect(await reconcileBusinessSession()).toBe(false)
  expect(businessState.value).toBeNull()
  expect(getAccessToken()).toBe('')
})
test('a mobile request queued before invalidation cannot borrow the next login token', async () => {
  let used = ''
  http.defaults.adapter = async config => { used = String(config.headers.Authorization); return response(config, 200, { data: {} }) }
  const pending = http.get('/mobile/bootstrap')
  clearBusinessSession(); setSession({ access_token: 'new', refresh_token: 'new-refresh' })
  await expect(pending).rejects.toBeInstanceOf(Error)
  expect(used).not.toBe('Bearer new')
})
