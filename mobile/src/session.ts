const ACCESS_TOKEN_KEY = 'xiquan_mobile_access_token'
const REFRESH_TOKEN_KEY = 'xiquan_mobile_refresh_token'
const SESSION_EXPIRES_KEY = 'xiquan_mobile_session_expires_at'
const TERMINAL_KEY = 'xiquan_mobile_terminal_code'
const SESSION_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000

export interface MobileSessionTokens {
  access_token: string
  refresh_token: string
}

export function setSession(login: MobileSessionTokens) {
  localStorage.setItem(ACCESS_TOKEN_KEY, login.access_token)
  localStorage.setItem(REFRESH_TOKEN_KEY, login.refresh_token)
  let expiresAt = Date.now() + SESSION_MAX_AGE_MS
  try {
    const encoded = login.refresh_token.split('.')[1]!.replace(/-/g, '+').replace(/_/g, '/')
    const payload = JSON.parse(atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, '=')))
    if (Number.isFinite(payload.exp)) expiresAt = Math.min(expiresAt, payload.exp * 1000)
  } catch { /* 仅用于本机到期提示，服务器仍独立校验 JWT。 */ }
  localStorage.setItem(SESSION_EXPIRES_KEY, String(expiresAt))
}

export function setAccessToken(token: string) {
  localStorage.setItem(ACCESS_TOKEN_KEY, token)
}

export function hasUsableSession() {
  const expiresAt = Number(localStorage.getItem(SESSION_EXPIRES_KEY) || 0)
  if (!localStorage.getItem(REFRESH_TOKEN_KEY) || Date.now() >= expiresAt) {
    clearSession()
    return false
  }
  return true
}

export function getAccessToken() {
  if (!hasUsableSession()) return ''
  return localStorage.getItem(ACCESS_TOKEN_KEY) || ''
}

export function getRefreshToken() {
  if (!hasUsableSession()) return ''
  return localStorage.getItem(REFRESH_TOKEN_KEY) || ''
}

export function clearSession() {
  localStorage.removeItem(ACCESS_TOKEN_KEY)
  localStorage.removeItem(REFRESH_TOKEN_KEY)
  localStorage.removeItem(SESSION_EXPIRES_KEY)
  sessionStorage.removeItem(ACCESS_TOKEN_KEY)
}

export function getOrCreateTerminalCode() {
  let code = localStorage.getItem(TERMINAL_KEY)
  if (!code) {
    const id = crypto.randomUUID().replaceAll('-', '').slice(0, 16).toUpperCase()
    code = `MOBILE-${id}`
    localStorage.setItem(TERMINAL_KEY, code)
  }
  return code
}

// Keep the existing names available while callers move to the full session API.
export const getToken = getAccessToken
export const clearToken = clearSession
