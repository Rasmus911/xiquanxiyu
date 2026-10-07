import axios, { type InternalAxiosRequestConfig } from 'axios'
import { safeApiUrl } from './safe-url'
import version from '../version.json'
import { acceptBusinessState, assertCurrent, businessGeneration, businessState, clearBusinessSession, onBusinessSessionClear, type BusinessState } from './business/state'
import {
  getAccessToken,
  getRefreshToken,
  hasUsableSession,
  setAccessToken,
} from './session'

export function getApiBaseUrl() {
  const configured = localStorage.getItem('xiquan_mobile_server_url') || import.meta.env.VITE_API_BASE_URL
  if (configured) return safeApiUrl(String(configured))
  if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
    return 'https://api.pqxqxy.xyz/api'
  }
  return safeApiUrl(`${location.origin}/api`)
}

export const http = axios.create({ timeout: 15000 })
let refreshPromise: Promise<string> | null = null
onBusinessSessionClear(() => { refreshPromise = null })

interface RetryableConfig extends InternalAxiosRequestConfig {
  _xiquanRetry?: boolean
  _businessGeneration?: number
}

export async function refreshAccessToken() {
  const generation = businessGeneration.capture()
  if (!hasUsableSession()) throw new Error('SESSION_EXPIRED')
  if (!refreshPromise) {
    const owned = axios.post(
      `${getApiBaseUrl()}/auth/refresh`,
      {},
      {
        headers: {
          Authorization: `Bearer ${getRefreshToken()}`,
          ...(businessState.value ? { 'X-Business-Period': businessState.value.period_id } : {}),
          'X-Client-Type': 'mobile', 'X-Client-Version': version.version, 'X-Request-ID': crypto.randomUUID(),
        },
        timeout: 15000,
      },
    ).then((response) => {
      assertCurrent(generation)
      const token = String(response.data?.data?.access_token || '')
      if (!token) throw new Error('REFRESH_TOKEN_MISSING')
      const data = response.data.data
      if (!Array.isArray(data.permissions)) throw new Error('服务器未提供账号权限，请重新登录')
      const state = businessState.value
      if (state && (data.business_state?.period_id !== state.period_id || data.business_state?.policy_version !== state.policy_version)) {
        throw new Error('经营期或权限已变化，请重新登录')
      }
      acceptBusinessState(data.business_state, data.permissions)
      setAccessToken(token)
      window.dispatchEvent(new Event('xiquan:token-refreshed'))
      return token
    }).finally(() => {
      if (businessGeneration.isCurrent(generation) && refreshPromise === owned) refreshPromise = null
    })
    refreshPromise = owned
  }
  return refreshPromise
}

http.interceptors.request.use((config) => {
  const scoped = config as RetryableConfig
  if (scoped._businessGeneration === undefined) scoped._businessGeneration = businessGeneration.capture()
  assertCurrent(scoped._businessGeneration)
  config.baseURL = getApiBaseUrl()
  const token = getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  if (token && businessState.value) config.headers['X-Business-Period'] = businessState.value.period_id
  config.headers['X-Request-ID'] = crypto.randomUUID()
  config.headers['X-Client-Type'] = 'mobile'
  config.headers['X-Client-Version'] = version.version
  return config
}, error => { throw error }, { synchronous: true })

http.interceptors.response.use(
  (response) => {
    assertCurrent((response.config as RetryableConfig)._businessGeneration!)
    const state = businessState.value
    const period = response.headers['x-business-period']
    const policy = response.headers['x-access-policy-version']
    if (state && ((period && period !== state.period_id) || (policy && Number(policy) !== state.policy_version))) {
      clearBusinessSession()
      window.dispatchEvent(new Event('xiquan:logged-out'))
      throw new Error('经营期或账号权限已变化，请重新登录')
    }
    return response
  },
  async (error) => {
    const config = error.config as RetryableConfig | undefined
    const generation = config?._businessGeneration ?? businessGeneration.capture()
    assertCurrent(generation)
    const code = error.response?.data?.error?.code
    if (['BUSINESS_PERIOD_CHANGED', 'CHANNEL_FORBIDDEN', 'ACCESS_POLICY_NOT_CONFIGURED',
      'SESSION_REVOKED', 'SESSION_EXPIRED', 'ACCOUNT_DISABLED', 'TERMINAL_DISABLED', 'ACCOUNT_LOCKED'].includes(code)) {
      error._businessSessionClearedGeneration = generation
      clearBusinessSession()
      window.dispatchEvent(new Event('xiquan:logged-out'))
      return Promise.reject(error)
    }
    const url = String(config?.url || '')
    const canRefresh = error.response?.status === 401
      && config
      && !config._xiquanRetry
      && !url.includes('/auth/login')
      && !url.includes('/auth/refresh')
    if (canRefresh) {
      config._xiquanRetry = true
      try {
        const token = await refreshAccessToken()
        assertCurrent(generation)
        config.headers.Authorization = `Bearer ${token}`
        return await http(config)
      } catch {
        if (businessGeneration.isCurrent(generation)) {
          error._businessSessionClearedGeneration = generation
          clearBusinessSession()
          window.dispatchEvent(new Event('xiquan:logged-out'))
        }
      }
    }
    return Promise.reject(error)
  },
)

export function dataOf<T>(response: { data: { data: T } }): T {
  return response.data.data
}
export async function reconcileBusinessSession() {
  if (!hasUsableSession()) return false
  const generation = businessGeneration.capture()
  try {
    if (!businessState.value) await refreshAccessToken()
    assertCurrent(generation)
    const state = dataOf<BusinessState>(await http.get('/business/state'))
    assertCurrent(generation)
    const previous = businessState.value
    if (!previous || state.period_id !== previous.period_id || state.policy_version !== previous.policy_version || state.maintenance) throw new Error('经营期、权限或维护状态已变化')
    acceptBusinessState(state)
    return true
  } catch {
    if (businessGeneration.isCurrent(generation)) { clearBusinessSession(); window.dispatchEvent(new Event('xiquan:logged-out')) }
    return false
  }
}

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (error.code === 'ECONNABORTED') return '连接云端超时，请检查手机网络后重试'
    const steps: Record<string, string> = {
      CHANNEL_FORBIDDEN: '手机入口尚未授权。请管理员核对该账号UUID绑定和手机入口权限。',
      ACCESS_POLICY_NOT_CONFIGURED: '云端权限策略尚未正确激活。请管理员执行只读通道诊断并核对绑定。',
      TERMINAL_INVALID: '手机终端未注册或已停用。请管理员核对终端状态，不要重复创建员工账号。',
      TERMINAL_DISABLED: '当前手机终端已停用，请联系管理员恢复终端。',
      SESSION_REVOKED: '账号授权或登录状态已变更，请重新登录。',
      ACCOUNT_DISABLED: '该员工账号已停用或删除，请联系管理员。',
    }
    const step = steps[String(error.response?.data?.error?.code)]
    if (step) return step
    if (!error.response && error.message === 'Network Error') return '无法连接云端，请检查手机网络及服务器地址。网络错误不等于账号没有权限。'
    return error.response?.data?.message || error.message || '网络请求失败'
  }
  return error instanceof Error ? error.message : '操作失败'
}
