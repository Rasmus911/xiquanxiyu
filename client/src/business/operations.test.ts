import { expect, test, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElMessageBox, ElMessage } from 'element-plus'
import CatalogView from '../views/CatalogView.vue'
import { http } from '../api/http'
import { dispatchRealtimeSnapshot } from '../realtime/events'
import ReportsView from '../views/ReportsView.vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import MemberPassPurchaseView from '../views/MemberPassPurchaseView.vue'
import { useRuntimeStore } from '../stores/runtime'
test('an older catalog query cannot overwrite the more recent refresh', async () => {
  const releases: Array<() => void> = []
  http.defaults.adapter = config => new Promise(resolve => {
    const name = releases.length ? 'new catalog' : 'old catalog'
    releases.push(() => resolve({ config, headers: {}, status: 200, statusText: '', data: { data: [{ id: name, name, kind: 'service', category: '服务', mobile_scope: 'both', price: '20.00', stock_tracked: false, stock_quantity: '0', low_stock_threshold: '0', sort_order: 1, is_active: true }] } }))
  })
  const wrapper = mount(CatalogView, { global: { plugins: [ElementPlus] } })
  try {
    await flushPromises(); dispatchRealtimeSnapshot(); await flushPromises()
    expect(releases).toHaveLength(2)
    releases[1]!(); await flushPromises()
    expect(wrapper.text()).toContain('new catalog')
    releases[0]!(); await flushPromises()
    expect(wrapper.text()).toContain('new catalog')
    expect(wrapper.text()).not.toContain('old catalog')
  } finally { wrapper.unmount() }
})
test('successful payment navigation releases its owned desktop busy state after unmount', async () => {
  const confirmation = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as any)
  const pinia = createPinia()
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/purchase/:id', component: MemberPassPurchaseView }, { path: '/members', component: { template: '<div>会员列表</div>' } }] })
  await router.push('/purchase/m1')
  http.defaults.adapter = async config => ({ config, headers: {}, status: 200, statusText: '', data: { data: config.method === 'get' ? { id: 'm1', name: '会员', phone: '13800138000', balance: '0.00' } : {} } })
  const wrapper = mount({ template: '<router-view />' }, { global: { plugins: [ElementPlus, pinia, router] } })
  try {
    await flushPromises()
    const button = wrapper.findAll('button').find(row => row.text() === '确认收款并开卡')!
    await button.trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('会员列表')
    expect(useRuntimeStore().businessBusyReason).toBeNull()
  } finally { wrapper.unmount(); confirmation.mockRestore(); ElMessage.closeAll() }
})
test('the latest silent report refresh owns completion of an earlier visible loading state', async () => {
  const releases: Array<() => void> = []
  http.defaults.adapter = config => new Promise(resolve => {
    const data = String(config.url).endsWith('summary') ? {} : []
    releases.push(() => resolve({ config, headers: {}, status: 200, statusText: '', data: { data } }))
  })
  const wrapper = mount(ReportsView, { global: { plugins: [ElementPlus, createPinia()] } })
  try {
    await flushPromises(); dispatchRealtimeSnapshot()
    await new Promise(resolve => setTimeout(resolve, 400))
    expect(releases).toHaveLength(8)
    releases.slice(4).forEach(release => release()); await flushPromises()
    expect((wrapper.vm as any).loading).toBe(false)
    releases.slice(0, 4).forEach(release => release()); await flushPromises()
    expect((wrapper.vm as any).loading).toBe(false)
  } finally { wrapper.unmount() }
})
