import { getCurrentScope, onBeforeUnmount, onScopeDispose, ref } from 'vue'
import { clearSession } from '../session'

export interface BusinessState {
  period_id: string
  business_revision: number
  policy_version: number
  maintenance: boolean
  owner_reset_allowed: boolean
}
export class BusinessGeneration {
  private value = 0
  capture() { return this.value }
  invalidate() { this.value += 1 }
  isCurrent(generation: number) { return generation === this.value }
}

export const businessGeneration = new BusinessGeneration()
export const businessState = ref<BusinessState | null>(null)
export const permissions = ref<string[]>([])
export const sessionEpoch = ref(0)
const clearListeners = new Set<() => void>()
export function onBusinessSessionClear(clear: () => void) {
  clearListeners.add(clear)
  const remove = () => { clearListeners.delete(clear) }
  if (getCurrentScope()) onScopeDispose(remove)
  return remove
}
export function clearBusinessSession() {
  businessGeneration.invalidate()
  sessionEpoch.value += 1
  businessState.value = null
  permissions.value = []
  clearSession()
  for (const storage of [localStorage, sessionStorage]) {
    for (const key of Object.keys(storage)) {
      if (key === 'xiquan_mobile_employee' || key.startsWith('xiquan_mobile_pending_')) storage.removeItem(key)
    }
  }
  clearListeners.forEach(clear => clear())
  window.dispatchEvent(new Event('xiquan:session-cleared'))
}
export class StaleBusinessResponse extends Error {
  constructor() { super('登录或经营期已变化，请重新查询') }
}
export function assertCurrent(generation: number) {
  if (!businessGeneration.isCurrent(generation)) throw new StaleBusinessResponse()
}
// A current request may clear its own session before callers handle its failure.
// Preserve that failure only until another login/invalidation advances again.
export function ensureSessionFailureCurrent(error: unknown, generation: number) {
  const owned = (error as { _businessSessionClearedGeneration?: number } | null)?._businessSessionClearedGeneration
  if (!businessGeneration.isCurrent(generation) && !(owned === generation && businessGeneration.capture() === generation + 1)) throw new StaleBusinessResponse()
}
export function acceptBusinessState(state: BusinessState, scope?: string[]) {
  if (!state?.period_id || !Number.isInteger(state.policy_version) || !Number.isInteger(state.business_revision)
    || typeof state.owner_reset_allowed !== 'boolean' || typeof state.maintenance !== 'boolean') {
    throw new Error('服务器未提供经营期信息，请更新后重新登录')
  }
  businessState.value = state
  if (scope) permissions.value = [...scope]
}
export function canAccess(permission: string) {
  return !!businessState.value && (permissions.value.includes('*') || permissions.value.includes(permission))
}
export function useBusinessGuard() {
  const generation = businessGeneration.capture()
  let active = true
  const operations = new Map<string, number>()
  onBeforeUnmount(() => { active = false })
  return (name: string) => {
    const owned = (operations.get(name) || 0) + 1
    operations.set(name, owned)
    return () => active && businessGeneration.isCurrent(generation) && operations.get(name) === owned
  }
}
