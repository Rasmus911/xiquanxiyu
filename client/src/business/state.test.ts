import { expect, test } from 'vitest'
import { BusinessGeneration, clearBusinessSession } from './state'
import { getAccessToken, setAccessToken } from '../auth/session'
test('ignores an old response after invalidation and a new login', () => {
  const requests = new BusinessGeneration()
  const old = requests.capture()
  requests.invalidate()
  expect(requests.isCurrent(old)).toBe(false)
  expect(requests.isCurrent(requests.capture())).toBe(true)
})
test('clears pending business operations and token but preserves terminal and reset query', () => {
  setAccessToken('old')
  sessionStorage.setItem('xiquan:pending-request:checkout', 'old-key')
  localStorage.setItem('xiquan_printer_name', 'USB')
  localStorage.setItem('xiquan_reset_query', 'random-query')
  clearBusinessSession()
  expect(getAccessToken()).toBe('')
  expect(sessionStorage.getItem('xiquan:pending-request:checkout')).toBeNull()
  expect(localStorage.getItem('xiquan_printer_name')).toBe('USB')
  expect(localStorage.getItem('xiquan_reset_query')).toBe('random-query')
})
