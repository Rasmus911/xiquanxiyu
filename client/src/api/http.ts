import axios, { type InternalAxiosRequestConfig } from 'axios'
import { getAccessToken } from '../auth/session'
import { acceptBusinessState, assertCurrent, businessGeneration, businessState, clearBusinessSession, type BusinessState } from '../business/state'
import { safeApiUrl } from './safe-url'
import build from '../../package.json'

export function getApiBaseUrl() {
  return safeApiUrl(localStorage.getItem('xiquan_server_url')
    || import.meta.env.VITE_API_BASE_URL
    || 'http://127.0.0.1:5000/api')
}

export const http = axios.create({
  timeout: 12000,
})
interface BusinessConfig extends InternalAxiosRequestConfig { _businessGeneration?: number }

http.interceptors.request.use((config) => {
  const scoped = config as BusinessConfig
  if (scoped._businessGeneration === undefined) scoped._businessGeneration = businessGeneration.capture()
  assertCurrent(scoped._businessGeneration)
  config.baseURL = getApiBaseUrl()
  const token = getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  if (token && businessState.value) config.headers['X-Business-Period'] = businessState.value.period_id
  config.headers['X-Request-ID'] = crypto.randomUUID()
  config.headers['X-Client-Type'] = window.xiquan ? 'desktop' : 'web'
  config.headers['X-Client-Version'] = build.version
  return config
}, error => { throw error }, { synchronous: true })

http.interceptors.response.use(
  (response) => {
    assertCurrent((response.config as BusinessConfig)._businessGeneration!)
    const state = businessState.value
    const period = response.headers['x-business-period']
    const policy = response.headers['x-access-policy-version']
    if (state && ((period && period !== state.period_id) || (policy && Number(policy) !== state.policy_version))) {
      clearBusinessSession()
      window.location.hash = '#/login'
      throw new Error('经营期或账号权限已变化，请重新登录')
    }
    return response
  },
  (error) => {
    if (error.config?._businessGeneration !== undefined) assertCurrent(error.config._businessGeneration)
    const code = error.response?.data?.error?.code
    if ((error.response?.status === 401 && !String(error.config?.url).includes('/auth/login')) || ['BUSINESS_PERIOD_CHANGED', 'CHANNEL_FORBIDDEN', 'ACCESS_POLICY_NOT_CONFIGURED'].includes(code)) {
      error._businessSessionClearedGeneration = error.config?._businessGeneration ?? businessGeneration.capture()
      clearBusinessSession()
      window.location.hash = '#/login'
    }
    return Promise.reject(error)
  },
)

export function apiData<T>(response: { data: { data: T } }): T {
  return response.data.data
}
export async function reconcileBusinessSession() {
  if (!getAccessToken()) return false
  const generation = businessGeneration.capture()
  try {
    const state = apiData<BusinessState>(await http.get('/business/state'))
    assertCurrent(generation)
    const previous = businessState.value
    if (!previous || state.period_id !== previous.period_id || state.policy_version !== previous.policy_version || state.maintenance) throw new Error('经营期、权限或维护状态已变化')
    acceptBusinessState(state)
    return true
  } catch {
    if (businessGeneration.isCurrent(generation)) { clearBusinessSession(); window.location.hash = '#/login' }
    return false
  }
}

export function apiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    return error.response?.data?.message || error.message || '网络请求失败'
  }
  return error instanceof Error ? error.message : '操作失败'
}
