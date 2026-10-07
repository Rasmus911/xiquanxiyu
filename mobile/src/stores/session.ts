import { defineStore } from 'pinia'
import { ref } from 'vue'
import { dataOf, http } from '../api'
import { getAccessToken, getOrCreateTerminalCode, hasUsableSession, setSession } from '../session'
import { acceptBusinessState, assertCurrent, businessGeneration, clearBusinessSession, ensureSessionFailureCurrent, onBusinessSessionClear, type BusinessState } from '../business/state'
import type { MobileEmployee } from '../types'

const EMPLOYEE_KEY = 'xiquan_mobile_employee'

function readEmployee() {
  try { return JSON.parse(localStorage.getItem(EMPLOYEE_KEY) || 'null') as MobileEmployee | null } catch { return null }
}

export const useSessionStore = defineStore('mobile-session', () => {
  const employee = ref<MobileEmployee | null>(readEmployee())
  const authenticated = ref(hasUsableSession())
  onBusinessSessionClear(() => { authenticated.value = false; setEmployee(null) })

  function setEmployee(value: MobileEmployee | null) {
    employee.value = value
    if (value) localStorage.setItem(EMPLOYEE_KEY, JSON.stringify(value))
    else localStorage.removeItem(EMPLOYEE_KEY)
  }

  async function login(username: string, password: string) {
    clearBusinessSession()
    const generation = businessGeneration.capture()
    try {
    const terminalCode = getOrCreateTerminalCode()
    await http.post('/terminals/register', { code: terminalCode, name: `手机点单端 ${terminalCode.slice(-6)}` })
    assertCurrent(generation)
    const result = dataOf<{ access_token: string; refresh_token: string; employee: MobileEmployee; business_state: BusinessState; permissions: string[] }>(await http.post('/auth/login', {
      username: username.trim(), password, terminal_code: terminalCode, client_channel: 'mobile',
    }))
    assertCurrent(generation)
    if (!Array.isArray(result.permissions)) throw new Error('服务器未提供账号权限，请重新登录')
    acceptBusinessState(result.business_state, result.permissions)
    setSession(result)
    setEmployee(result.employee)
    authenticated.value = true
    } catch (error) {
      ensureSessionFailureCurrent(error, generation)
      if (businessGeneration.isCurrent(generation)) clearBusinessSession()
      throw error
    }
  }

  async function logout() {
    const token = getAccessToken()
    const revoke = token ? http.post('/auth/logout', {}, { headers: { Authorization: `Bearer ${token}` } }) : Promise.resolve()
    clearBusinessSession()
    try { await revoke } catch { /* 无网络退出不能保证服务端立即吊销。 */ }
  }

  return { authenticated, employee, login, logout, setEmployee }
})
