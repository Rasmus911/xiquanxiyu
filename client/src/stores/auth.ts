import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { apiData, http } from '../api/http'
import { getAccessToken, setAccessToken } from '../auth/session'
import { acceptBusinessState, assertCurrent, businessGeneration, clearBusinessSession, ensureSessionFailureCurrent, onBusinessSessionClear, type BusinessState } from '../business/state'
import type { Employee, Terminal } from '../types'
import { assertSessionUi } from '../navigation/access'

export const useAuthStore = defineStore('auth', () => {
  const employee = ref<Employee | null>(null)
  const terminal = ref<Terminal | null>(null)
  const isLoggedIn = computed(() => Boolean(employee.value && getAccessToken()))
  onBusinessSessionClear(() => { employee.value = null; terminal.value = null })

  async function login(username: string, password: string, terminalCode: string) {
    clearBusinessSession()
    const generation = businessGeneration.capture()
    try {
    const data = apiData<{
      access_token: string
      refresh_token: string
      employee: Employee
      terminal: Terminal
      business_state: BusinessState
      permissions: string[]
    }>(await http.post('/auth/login', { username, password, terminal_code: terminalCode, client_channel: window.xiquan ? 'desktop' : 'web' }))
    assertCurrent(generation)
    if (!Array.isArray(data.permissions)) throw new Error('服务器未提供账号权限，请重新登录')
    assertSessionUi(data.business_state)
    acceptBusinessState(data.business_state, data.permissions)
    setAccessToken(data.access_token)
    employee.value = data.employee
    terminal.value = data.terminal
    } catch (error) {
      ensureSessionFailureCurrent(error, generation)
      if (businessGeneration.isCurrent(generation)) clearBusinessSession()
      throw error
    }
  }

  async function restore() {
    return false
  }

  async function logout(reload = true) {
    const token = getAccessToken()
    const revoke = token ? http.post('/auth/logout', {}, { headers: { Authorization: `Bearer ${token}` } }) : Promise.resolve()
    clearBusinessSession()
    if (reload) window.location.href = '#/login'
    try { await revoke } catch { /* 断网退出不能保证服务端立即吊销，令牌按有效期失效。 */ }
  }

  return { employee, terminal, isLoggedIn, login, restore, logout }
})
