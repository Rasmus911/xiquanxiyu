// @vitest-environment jsdom

import { beforeEach, expect, test, vi } from 'vitest'
import { clearSession, getAccessToken, hasUsableSession, setSession } from './session'

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-09-19T00:00:00Z'))
})

test('session survives an app restart within seven days', () => {
  setSession({ access_token: 'access', refresh_token: 'refresh' })

  expect(getAccessToken()).toBe('access')
  expect(hasUsableSession()).toBe(true)
})

test('session expires locally after seven days', () => {
  setSession({ access_token: 'access', refresh_token: 'refresh' })

  vi.setSystemTime(new Date('2026-09-26T00:00:01Z'))

  expect(hasUsableSession()).toBe(false)
  expect(getAccessToken()).toBe('')
})

test('logout clears tokens but keeps terminal identity', () => {
  localStorage.setItem('xiquan_mobile_terminal_code', 'MOBILE-TEST-01')
  setSession({ access_token: 'access', refresh_token: 'refresh' })

  clearSession()

  expect(getAccessToken()).toBe('')
  expect(localStorage.getItem('xiquan_mobile_terminal_code')).toBe('MOBILE-TEST-01')
})

test('an eight-hour administrator refresh token also limits the local session', () => {
  const exp = Math.floor(Date.now() / 1000) + 8 * 3600
  setSession({ access_token: 'access', refresh_token: `header.${btoa(JSON.stringify({ exp }))}.signature` })
  vi.advanceTimersByTime(8 * 3600 * 1000 + 1)
  expect(hasUsableSession()).toBe(false)
})
