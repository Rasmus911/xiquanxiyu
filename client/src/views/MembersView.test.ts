import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, expect, it } from 'vitest'
import { http } from '../api/http'
import { clearBusinessSession } from '../business/state'
import PhysicalMemberDialog from '../components/members/PhysicalMemberDialog.vue'
import CardScanDialog from '../components/members/CardScanDialog.vue'
import MemberDetailDrawer from '../components/members/MemberDetailDrawer.vue'
import MembersView from './MembersView.vue'

const member = { id: 'member-1', phone: '', name: '', balance: '125.50', is_active: true, holder_surname: null,
  card_binding: { id: 'binding-1', member_id: 'member-1', card_uid: '000315346091', is_active: true, created_at: '2026-10-12T00:00:00Z', revoked_at: null, replaced_by_id: null, version: 1 } }
const result = { member, card_binding: member.card_binding, member_pass: null }
let cleanup = () => {}
const originalAdapter = http.defaults.adapter
afterEach(() => { cleanup(); clearBusinessSession(); http.defaults.adapter = originalAdapter; localStorage.clear(); sessionStorage.clear() })
async function prepare(w: VueWrapper<any>) {
  await w.find('[data-testid="physical-scan"]').trigger('click'); await flushPromises()
  const input = w.findComponent(CardScanDialog).find('input')
  await input.setValue('000315346091'); await input.trigger('keydown', { key: 'Enter' }); await flushPromises()
  await w.find('[name="amount"]').setValue('125.50')
  await w.find('[data-testid="physical-next"]').trigger('click'); await flushPromises()
}
it('shows the binding action with missing phone safely while retaining existing member actions', async () => {
  const w = mount(MemberDetailDrawer, { props: { modelValue: true, member: { ...member, card_binding: null }, activeTab: 'stored' }, global: { plugins: [ElementPlus], stubs: { teleport: true } } }); cleanup = () => w.unmount(); await flushPromises()
  expect(w.text()).toContain('未留手机号')
  await w.find('[data-testid="member-card-binding"]').trigger('click'); expect(w.emitted('bindCard')).toEqual([[{ ...member, card_binding: null }]])
  const recharge = w.findAll('button').find(button => button.text().includes('储值充值'))!
  await recharge.trigger('click'); expect(w.emitted('recharge')).toHaveLength(1)
  await w.setProps({ member }); expect(w.find('[data-testid="member-card-binding"]').text()).toContain('补办实体卡')
})
it('blocks real route navigation for pending or uncertain opening and refreshes the same account once reconciled', async () => {
  const pinia = createPinia(); setActivePinia(pinia)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/members', component: MembersView }, { path: '/other', component: { template: '<p>other page</p>' } }] })
  const requests: string[] = []; let attempts = 0, reject!: (error: Error) => void
  http.defaults.adapter = async config => {
    requests.push(`${config.method} ${config.url}`)
    if (config.url === '/members/physical-open') { attempts++; if (attempts === 1) await new Promise((_resolve, r) => { reject = r }) }
    const data = config.url === '/members' ? [member] : config.url === '/members/member-1' ? { ...member, passes: [], ledgers: [] } : result
    return { config, status: 200, statusText: '', headers: {}, data: { data } }
  }
  await router.push('/members'); await router.isReady()
  const w = mount(defineComponent({ template: '<router-view />' }), { global: { plugins: [ElementPlus, pinia, router], stubs: { teleport: true } } }); cleanup = () => w.unmount(); await flushPromises()
  expect(w.text()).toContain('手机号开通会员'); expect(w.text()).toContain('未留手机号')
  expect(w.find('.el-table__body').text()).toContain('000315346091')
  await w.find('[data-testid="physical-member-open"]').trigger('click'); await flushPromises()
  const dialog = w.findComponent(PhysicalMemberDialog); await prepare(dialog)
  await dialog.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises()
  await router.push('/other'); await flushPromises(); expect(router.currentRoute.value.path).toBe('/members')
  reject(new Error('timeout')); await flushPromises()
  await router.push('/other'); await flushPromises(); expect(router.currentRoute.value.path).toBe('/members')
  await dialog.find('[data-testid="physical-retry"]').trigger('click'); await flushPromises()
  expect(requests.filter(request => request.startsWith('post'))).toEqual(['post /members/physical-open', 'post /members/physical-open'])
  expect(w.findComponent(MemberDetailDrawer).props('member')?.id).toBe('member-1')
  expect(w.findComponent(MemberDetailDrawer).props('modelValue')).toBe(true)
  await router.push('/other'); await flushPromises(); expect(router.currentRoute.value.path).toBe('/other')
})
it('discards physical-opening detail refresh after drawer closes and reopens', async () => {
  const pinia = createPinia(); setActivePinia(pinia)
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/members', component: MembersView }] })
  let finish!: () => void
  http.defaults.adapter = config => {
    if (config.url === '/members/member-1') return new Promise(r => { finish = () => r({ config, status: 200, statusText: '', headers: {}, data: { data: { ...member, balance: '999.00' } } }) })
    return Promise.resolve({ config, status: 200, statusText: '', headers: {}, data: { data: config.url === '/members' ? [member] : result } })
  }
  await router.push('/members'); await router.isReady()
  const w = mount(defineComponent({ template: '<router-view />' }), { global: { plugins: [ElementPlus, pinia, router], stubs: { teleport: true } } }); cleanup = () => w.unmount(); await flushPromises()
  await w.find('[data-testid="physical-member-open"]').trigger('click'); await flushPromises()
  const dialog = w.findComponent(PhysicalMemberDialog); await prepare(dialog); await dialog.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises()
  const drawer = w.findComponent(MemberDetailDrawer)
  drawer.vm.$emit('update:modelValue', false); drawer.vm.$emit('update:modelValue', true)
  finish(); await flushPromises()
  expect(drawer.props('member')?.balance).toBe('125.50')
})
