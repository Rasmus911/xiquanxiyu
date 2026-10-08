import { createRouter, createWebHashHistory } from 'vue-router'
import { mobileLanding, routeAccess, type MobileRouteName } from './access'
import { useSessionStore } from '../stores/session'
import MobileShell from '../layouts/MobileShell.vue'
import { businessState, canAccess, permissions } from '../business/state'
import { scopedMobileCapabilities } from '../mobile-management'
import { reconcileBusinessSession } from '../api'

const router = createRouter({ history: createWebHashHistory(), routes: [
  { path: '/download', name: 'download', component: () => import('../views/DownloadView.vue') },
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  { path: '/', component: MobileShell, children: [
    { path: '', redirect: '/orders' },
    { path: 'orders', name: 'orders', component: () => import('../views/OrdersView.vue') },
    { path: 'orders/:visitId', name: 'visit-order', component: () => import('../views/VisitOrderView.vue') },
    { path: 'reports', name: 'reports', component: () => import('../views/ReportsView.vue') },
    { path: 'inventory', name: 'inventory', component: () => import('../views/InventoryView.vue') },
    { path: 'catalog', name: 'catalog', component: () => import('../views/CatalogView.vue') },
    { path: 'profile', name: 'profile', component: () => import('../views/ProfileView.vue') },
    { path: 'registration-token', name: 'registration-token', component: () => import('../views/RegistrationTokenView.vue') },
  ] },
  { path: '/:pathMatch(.*)*', redirect: '/orders' },
] })

router.beforeEach(async (to) => {
  const session = useSessionStore()
  if (session.authenticated && !businessState.value && !['login', 'download'].includes(String(to.name))) await reconcileBusinessSession()
  const capabilities = scopedMobileCapabilities(session.employee?.capabilities, permissions.value)
  const landing = mobileLanding(capabilities)
  if (session.authenticated && ['reports', 'inventory', 'catalog', 'orders', 'visit-order'].includes(String(to.name))
    && !canAccess(to.name === 'reports' ? 'report:read' : to.name === 'inventory' ? 'inventory:read' : to.name === 'catalog' ? 'catalog:write' : 'mobile:order')) {
    return { path: landing, query: { notice: '无权访问该功能' } }
  }
  const accessSession = session.authenticated ? { capabilities } : null
  const decision = routeAccess(to.name as MobileRouteName, accessSession)
  if (decision === 'login') return { name: 'login' }
  if (decision === 'orders') return { name: 'orders' }
  if (decision === 'inventory') return { name: 'inventory' }
  if (decision === 'forbidden') return { path: landing, query: { notice: '无权访问该功能' } }
  return true
})
export default router
