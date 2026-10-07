import { useBusinessStore } from '../stores/business'
import { useSessionStore } from '../stores/session'
import { reconcileBusinessSession } from '../api'
import { businessGeneration, clearBusinessSession } from '../business/state'

export function useBootstrap() {
  const business = useBusinessStore()
  const session = useSessionStore()

  async function initialise() {
    if (!session.authenticated) return false
    const generation = businessGeneration.capture()
    try {
      if (!await reconcileBusinessSession() || !businessGeneration.isCurrent(generation)) return false
      await business.refreshBootstrap()
    } catch (error) {
      if (businessGeneration.isCurrent(generation)) clearBusinessSession()
      throw error
    }
    return true
  }

  return { initialise }
}
