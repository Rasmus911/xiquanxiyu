import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElMessage } from 'element-plus'
import { Download, Right } from '@element-plus/icons-vue'
import { defineComponent } from 'vue'
import LoginView from './LoginView.vue'
import UpdateCenter from '../components/update/UpdateCenter.vue'

afterEach(() => { delete (window as any).xiquan; ElMessage.closeAll(); vi.restoreAllMocks() })
it('uses the approved name and groups everyday actions separately from setup', async () => {
  ;(window as any).xiquan = {getConfig: vi.fn(async () => null)}
  const router = createRouter({history:createMemoryHistory(),routes:[{path:'/login',component:LoginView}]})
  await router.push('/login'); await router.isReady()
  const wrapper = mount(LoginView,{global:{plugins:[createPinia(),router,ElementPlus]}})
  try {
    await flushPromises()
    expect(wrapper.find('h1').text()).toBe('平泉市溪泉洗浴')
    expect(wrapper.text()).not.toContain('手牌、收银、会员、库存与经营报表')
    expect(wrapper.find('[data-testid="login-primary-actions"]').text()).toContain('注册账号')
    expect(wrapper.find('[data-testid="login-primary-actions"]').text()).toContain('检查更新')
    expect(wrapper.find('[data-testid="login-setup-actions"]').text()).toContain('服务器与终端设置')
    expect(wrapper.find('[data-testid="login-setup-actions"]').text()).toContain('首次初始化管理员')
    expect(wrapper.find('input[type=password]').attributes('autocomplete')).toBe('current-password')
  } finally { wrapper.unmount() }
})

it('opens the offline release history from login without an authenticated session', async () => {
  window.xiquan = {
    getConfig: async () => ({}), getUpdateState: async () => { throw Error('offline') },
    checkForUpdates: async () => { throw Error('offline') }, onUpdateState: () => () => {},
  } as unknown as NonNullable<Window['xiquan']>
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/login', component: LoginView }] })
  await router.push('/login'); await router.isReady()
  const page = defineComponent({ components: { LoginView, UpdateCenter }, template: '<LoginView /><UpdateCenter />' })
  const wrapper = mount(page, { attachTo: document.body, global: {
    plugins: [createPinia(), router, ElementPlus], components: { Download, Right }, stubs: { teleport: true },
  } })
  try {
    await flushPromises()
    await wrapper.get('[data-testid="login-check-updates"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('.release-history').text()).toContain('增加实体卡消费功能')
    expect(wrapper.get('.release-history').text()).toContain('待发布')
    expect(router.currentRoute.value.path).toBe('/login')
    expect(wrapper.get('.dialog-actions').text()).toContain('关闭')
  } finally { wrapper.unmount() }
})
