export type MobileRouteName = 'download' | 'login' | 'orders' | 'visit-order' | 'reports' | 'inventory' | 'catalog' | 'profile' | 'registration-token'
export type RouteAccessDecision = 'allow' | 'login' | 'orders' | 'inventory' | 'forbidden'

interface AccessSession {
  capabilities?: {
    registration_token_view?: boolean
    orders_view?: boolean
    reports_view?: boolean
    inventory_manage?: boolean
    reports?: boolean
    inventory_add?: boolean
    catalog_manage?: boolean
  }
}

export function mobileLanding(caps?: AccessSession['capabilities']): '/inventory' | '/orders' | '/login' {
  if (caps?.orders_view === true) return '/orders'
  if (caps?.inventory_manage === true) return '/inventory'
  return '/login'
}

export function routeAccess(routeName: MobileRouteName, session: AccessSession | null): RouteAccessDecision {
  if (routeName === 'download') return 'allow'
  if (routeName === 'login') {
    const landing = session ? mobileLanding(session.capabilities) : '/login'
    return landing === '/orders' ? 'orders' : landing === '/inventory' ? 'inventory' : 'allow'
  }
  if (!session) return 'login'
  if (routeName === 'registration-token' && session.capabilities?.registration_token_view !== true) return 'forbidden'
  if (['orders', 'visit-order'].includes(routeName) && session.capabilities?.orders_view !== true) return 'forbidden'
  if (routeName === 'reports' && !(session.capabilities?.reports_view ?? session.capabilities?.reports)) return 'forbidden'
  if (routeName === 'inventory' && !(session.capabilities?.inventory_manage ?? session.capabilities?.inventory_add)) return 'forbidden'
  if (routeName === 'catalog' && session.capabilities?.catalog_manage !== true) return 'forbidden'
  return 'allow'
}
