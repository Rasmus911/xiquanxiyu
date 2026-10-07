import { expect, test } from 'vitest'
import { safeApiUrl } from './safe-url'

test('the phone refuses public plain HTTP and URLs containing credentials', () => {
  expect(safeApiUrl('https://api.pqxqxy.xyz/api/')).toBe('https://api.pqxqxy.xyz/api')
  expect(() => safeApiUrl('http://39.96.217.210/api')).toThrow()
  expect(() => safeApiUrl('https://user:secret@example.com/api')).toThrow()
})
