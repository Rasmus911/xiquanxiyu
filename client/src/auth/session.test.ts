import { beforeEach, describe, expect, it } from 'vitest'
import { clearAccessToken, getAccessToken, setAccessToken } from './session'

describe('登录会话', () => {
  beforeEach(() => {
    clearAccessToken()
    localStorage.clear()
  })

  it('只保存在当前运行内存中，不写入本地存储', () => {
    setAccessToken('temporary-token')
    expect(getAccessToken()).toBe('temporary-token')
    expect(localStorage.getItem('xiquan_access_token')).toBeNull()
    clearAccessToken()
    expect(getAccessToken()).toBe('')
  })
})
