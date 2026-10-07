import type { useBusinessStore } from './stores/business'
import type { useSessionStore } from './stores/session'
import { assertCurrent, businessGeneration, clearBusinessSession, ensureSessionFailureCurrent } from './business/state'

type SessionStore = ReturnType<typeof useSessionStore>
type BusinessStore = ReturnType<typeof useBusinessStore>

export async function loginAndLoad(
  session: SessionStore,
  business: BusinessStore,
  username: string,
  password: string,
) {
  const login = session.login(username, password)
  const generation = businessGeneration.capture()
  await login
  assertCurrent(generation)
  try { await business.refreshBootstrap(); assertCurrent(generation) }
  catch (error) {
    ensureSessionFailureCurrent(error, generation)
    if (businessGeneration.isCurrent(generation)) clearBusinessSession()
    throw error
  }
}
