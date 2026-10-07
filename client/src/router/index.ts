import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import ShellLayout from '../layouts/ShellLayout.vue'
import LoginView from '../views/LoginView.vue'
import { businessState } from '../business/state'
import { landingPath, pageAllowed } from '../navigation/access'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView, meta: { title: '员工登录' } },
    {
      path: '/',
      component: ShellLayout,
      children: [
        { path: '', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '前台手牌', section: '前台营业', roles: ['cashier', 'manager', 'admin'] } },
        { path: 'visits/:id', name: 'visit', component: () => import('../views/VisitView.vue'), meta: { title: '手牌消费', section: '前台营业', parentRoute: '/', roles: ['cashier', 'manager', 'admin'] } },
        { path: 'checkout', name: 'checkout', component: () => import('../views/CheckoutView.vue'), meta: { title: '收款结账', section: '前台营业', parentRoute: '/', roles: ['cashier', 'manager', 'admin'] } },
        { path: 'catalog', name: 'catalog', component: () => import('../views/CatalogView.vue'), meta: { title: '项目商品', section: '商品运营', parentRoute: '/', roles: ['manager', 'admin'] } },
        { path: 'members', name: 'members', component: () => import('../views/MembersView.vue'), meta: { title: '会员管理', section: '前台营业', parentRoute: '/', roles: ['cashier', 'manager', 'admin'] } },
        { path: 'members/:id/recharge', name: 'member-recharge', component: () => import('../views/MemberRechargeView.vue'), meta: { title: '会员储值', section: '前台营业', parentRoute: '/members', roles: ['cashier', 'manager', 'admin'] } },
        { path: 'members/:id/pass-purchase', name: 'member-pass-purchase', component: () => import('../views/MemberPassPurchaseView.vue'), meta: { title: '购买次卡', section: '前台营业', parentRoute: '/members', roles: ['cashier', 'manager', 'admin'] } },
        { path: 'inventory', name: 'inventory', component: () => import('../views/InventoryView.vue'), meta: { title: '库存管理', section: '商品运营', parentRoute: '/', roles: ['inventory', 'manager', 'admin'] } },
        { path: 'print-jobs', name: 'print-jobs', component: () => import('../views/PrintJobsView.vue'), meta: { title: '小票补打', section: '前台营业', parentRoute: '/', roles: ['cashier', 'manager', 'admin'] } },
        { path: 'reports', name: 'reports', component: () => import('../views/ReportsView.vue'), meta: { title: '经营报表', section: '经营管理', parentRoute: '/', roles: ['manager', 'admin'] } },
        { path: 'employees', name: 'employees', component: () => import('../views/EmployeesView.vue'), meta: { title: '员工账号', section: '系统', parentRoute: '/', roles: ['admin'] } },
        { path: 'audit', name: 'audit', component: () => import('../views/AuditView.vue'), meta: { title: '操作记录', section: '经营管理', parentRoute: '/', roles: ['manager', 'admin'] } },
        { path: 'settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { title: '系统设置', section: '系统', parentRoute: '/', roles: ['admin'] } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.path === '/login') return true
  if (!auth.isLoggedIn) {
    const restored = await auth.restore()
    if (!restored) return '/login'
  }
  const state = businessState.value
  if (!pageAllowed(state?.ui_pages || [], to.path, state?.capabilities || {})) return landingPath(state?.ui_pages || [])
  return true
})

export default router
