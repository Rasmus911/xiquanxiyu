import { expect, test } from 'vitest'
import { safeApiUrl } from './safe-url'

test('credentials only travel over HTTPS or a loopback development connection', () => {
  expect(safeApiUrl('https://api.pqxqxy.xyz/api/')).toBe('https://api.pqxqxy.xyz/api')
  expect(safeApiUrl('http://127.0.0.1:5001/api')).toBe('http://127.0.0.1:5001/api')
  for (const url of ['http://39.96.217.210/api', 'https://user:password@example.com/api', 'file:///api', 'https://example.com/api?q=1']) {
    expect(() => safeApiUrl(url)).toThrow()
  }
})
