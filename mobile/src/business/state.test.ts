import { expect, test } from 'vitest'
// @vitest-environment jsdom
import { BusinessGeneration, clearBusinessSession } from './state'
import { getAccessToken, setSession } from '../session'
test('ignores an old response after invalidation and a new login', () => {
  const requests = new BusinessGeneration()
  const old = requests.capture()
  requests.invalidate()
  expect(requests.isCurrent(old)).toBe(false)
  expect(requests.isCurrent(requests.capture())).toBe(true)
})
test('clears tokens employee cache and all operation keys but preserves terminal and reset query', () => {
  setSession({ access_token: 'old', refresh_token: 'old-refresh' })
  for (const key of ['xiquan_mobile_employee', 'xiquan_mobile_pending_order_key', 'xiquan_mobile_pending_order_fingerprint', 'xiquan_mobile_pending_operation_inventory']) localStorage.setItem(key, 'old')
  localStorage.setItem('xiquan_mobile_terminal_code', 'MOBILE-1')
  localStorage.setItem('xiquan_reset_query', 'random-query')
  clearBusinessSession()
  expect(getAccessToken()).toBe('')
  expect(localStorage.getItem('xiquan_mobile_employee')).toBeNull()
  expect(localStorage.getItem('xiquan_mobile_pending_operation_inventory')).toBeNull()
  expect(localStorage.getItem('xiquan_mobile_pending_order_key')).toBeNull()
  expect(localStorage.getItem('xiquan_mobile_terminal_code')).toBe('MOBILE-1')
  expect(localStorage.getItem('xiquan_reset_query')).toBe('random-query')
})
