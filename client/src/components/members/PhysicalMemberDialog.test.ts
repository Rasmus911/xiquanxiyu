import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, expect, it } from 'vitest'
import { http } from '../../api/http'
import { clearBusinessSession } from '../../business/state'
import { useRuntimeStore } from '../../stores/runtime'
import PhysicalMemberDialog from './PhysicalMemberDialog.vue'
import CardScanDialog from './CardScanDialog.vue'

const member = { id: 'member-1', phone: '', name: '', balance: '125.50', is_active: true, holder_surname: null,
  card_binding: { id: 'binding-1', member_id: 'member-1', card_uid: '000315346091', is_active: true, created_at: '2026-10-12T00:00:00Z', revoked_at: null, replaced_by_id: null, version: 1 } }
const result = { member, card_binding: member.card_binding, member_pass: null }
let cleanup = () => {}
const originalAdapter = http.defaults.adapter
const originalDesktop = window.xiquan
afterEach(() => { cleanup(); clearBusinessSession(); window.xiquan = originalDesktop; http.defaults.adapter = originalAdapter; localStorage.clear(); sessionStorage.clear() })
async function render() {
  const pinia = createPinia(); setActivePinia(pinia)
  const w = mount(PhysicalMemberDialog, { props: { modelValue: true }, global: { plugins: [ElementPlus, pinia], stubs: { teleport: true } } })
  cleanup = () => w.unmount(); await flushPromises(); return w
}
async function prepare(w: VueWrapper<any>, uid = '000315346091') {
  await w.find('[data-testid="physical-scan"]').trigger('click'); await flushPromises()
  const input = w.findComponent(CardScanDialog).find('input')
  await input.setValue(uid); await input.trigger('keydown', { key: 'Enter' }); await flushPromises()
  await w.find('[name="amount"]').setValue('125.50')
  await w.find('[data-testid="physical-next"]').trigger('click'); await flushPromises()
}
it('cancels collection confirmation without opening an account', async () => {
  const requests: unknown[] = []; http.defaults.adapter = async config => { requests.push(config); throw new Error('unexpected request') }
  const w = await render(); await prepare(w)
  expect(w.text()).toContain('未留手机号'); expect(w.text()).toContain('125.50')
  await w.find('[data-testid="physical-cancel"]').trigger('click'); await flushPromises()
  expect(requests).toEqual([]); expect(w.emitted('update:modelValue')).toEqual([[false]])
})
it('requires surname verification before collection', async () => {
  const w = await render(); await w.find('[name="holder_surname"]').setValue('张'); await prepare(w)
  expect(w.find('[data-testid="physical-confirm"]').exists()).toBe(false)
  await w.find('[name="surname_confirmed"]').setValue(true)
  await w.find('[data-testid="physical-next"]').trigger('click'); await flushPromises()
  expect(w.find('[data-testid="physical-confirm"]').exists()).toBe(true)
})
it('opens without a phone in one paid HTTP request and rejects repeated confirmation', async () => {
  const requests: any[] = []; let resolve!: (value: any) => void
  http.defaults.adapter = config => { requests.push({ url: config.url, body: JSON.parse(config.data) }); return new Promise(r => { resolve = data => r({ config, status: 201, statusText: '', headers: {}, data: { data } }) }) }
  const w = await render(); await prepare(w)
  await w.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises()
  await w.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises()
  expect(requests).toHaveLength(1); expect(useRuntimeStore().businessBusyReason).toBeTruthy()
  expect(requests[0]).toMatchObject({ url: '/members/physical-open', body: { phone: null, holder_surname: null, surname_confirmed: false, membership_type: 'stored', amount: '125.50', card_uid: '000315346091', payment_method: 'cash' } })
  expect(requests[0].body.idempotency_key).toBeTruthy()
  resolve(result); await flushPromises()
  expect(w.emitted('opened')).toEqual([[member]]); expect(useRuntimeStore().businessBusyReason).toBeNull()
})
it('submits actual paid pass price and count independently', async () => {
  let payload: any
  http.defaults.adapter = async config => { payload = JSON.parse(config.data); return { config, status: 201, statusText: '', headers: {}, data: { data: { ...result, member_pass: { id: 'pass-1', name: '洗浴次卡', remaining_count: 10, valid_until: null, is_active: true } } } } }
  const w = await render(); await w.find('select[name="membership_type"]').setValue('pass'); await w.find('[name="count"]').setValue('10'); await prepare(w)
  await w.find('select[name="payment_method"]').setValue('alipay')
  await w.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises()
  expect(payload).toMatchObject({ membership_type: 'pass', amount: '125.50', count: 10, payment_method: 'alipay', pass_name: '洗浴次卡', valid_until: null })
  expect(w.emitted('opened')).toEqual([[member]])
})
it('keeps an immutable body and original key after transport uncertainty and locks collection until explicit retry', async () => {
  const requests: any[] = []
  http.defaults.adapter = async config => { requests.push(JSON.parse(config.data)); if (requests.length === 1) throw new Error('timeout'); return { config, status: 200, statusText: '', headers: {}, data: { data: result } } }
  const w = await render(); await prepare(w); await w.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises()
  expect(requests).toHaveLength(1); expect(w.text()).toContain('原请求'); expect(useRuntimeStore().businessBusyReason).toBeTruthy()
  expect(w.find('select[name="payment_method"]').attributes('disabled')).toBeDefined()
  await w.find('select[name="payment_method"]').setValue('alipay')
  expect(w.find('[data-testid="physical-cancel"]').attributes('disabled')).toBeDefined()
  await w.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises(); expect(requests).toHaveLength(1)
  await w.find('[data-testid="physical-retry"]').trigger('click'); await flushPromises()
  expect(requests).toHaveLength(2); expect(requests[1]).toEqual(requests[0]); expect(w.emitted('opened')).toEqual([[member]])
})
it.each(['close', 'session', 'unmount'])('does not apply late opening to UI after %s', async action => {
  let resolve!: (value: any) => void
  http.defaults.adapter = config => new Promise(r => { resolve = data => r({ config, status: 201, statusText: '', headers: {}, data: { data } }) })
  const w = await render(); await prepare(w); await w.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises()
  if (action === 'close') { await w.setProps({ modelValue: false }); await w.setProps({ modelValue: true }) }
  else if (action === 'session') clearBusinessSession()
  else w.unmount()
  resolve(result); await flushPromises(); expect(w.emitted('opened')).toBeUndefined()
  if (action === 'close') expect(w.find('[data-testid="physical-retry"]').exists()).toBe(true)
})
it('does not release another operation busy protection when an older opening finishes', async () => {
  let resolve!: (value: any) => void
  http.defaults.adapter = config => new Promise(r => { resolve = data => r({ config, status: 201, statusText: '', headers: {}, data: { data } }) })
  const w = await render(); await prepare(w); await w.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises()
  await useRuntimeStore().setBusinessBusy('other operation')
  resolve(result); await flushPromises()
  expect(useRuntimeStore().businessBusyReason).toBe('other operation')
})
it('acquires fresh busy ownership after session changes during desktop synchronization', async () => {
  let finish!: (state: UpdateState) => void, busyCalls = 0
  const desktopState = (reason: string | null): UpdateState => ({ status: 'idle', decision: 'none', required: false, currentVersion: '0.5.1', availableVersion: null, releaseVersion: null, releasePublishedAt: null, percent: 0, message: '', releaseNotes: [], downloadUrl: '', businessBusyReason: reason })
  window.xiquan = { setBusinessBusy: (reason: string | null) => {
    if (reason) { busyCalls++; if (busyCalls === 1) return new Promise<UpdateState>(r => { finish = r }) }
    return Promise.resolve(desktopState(reason))
  } } as NonNullable<Window['xiquan']>
  let posted = 0
  http.defaults.adapter = async config => { posted++; throw new Error('timeout') }
  const w = await render(); await prepare(w); await w.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises()
  clearBusinessSession(); finish(desktopState('old opening')); await flushPromises(); expect(posted).toBe(0)
  await w.setProps({ modelValue: false }); await w.setProps({ modelValue: true }); await flushPromises(); await prepare(w)
  await w.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises()
  expect(posted).toBe(1); expect(busyCalls).toBe(2); expect(useRuntimeStore().businessBusyReason).toBeTruthy()
})
it('allows another card opening after a completed dialog closes and reopens', async () => {
  const requests: any[] = []
  http.defaults.adapter = async config => { requests.push(JSON.parse(config.data)); if (requests.length > 1) throw new Error('second pending'); return { config, status: 201, statusText: '', headers: {}, data: { data: result } } }
  const pinia = createPinia(); setActivePinia(pinia)
  const host = defineComponent({ components: { PhysicalMemberDialog }, setup: () => ({ open: ref(true) }), template: '<PhysicalMemberDialog v-model="open" />' })
  const w = mount(host, { global: { plugins: [ElementPlus, pinia], stubs: { teleport: true } } }); cleanup = () => w.unmount(); await flushPromises()
  const dialog = w.findComponent(PhysicalMemberDialog)
  await prepare(dialog); await dialog.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises()
  expect(w.vm.open).toBe(false)
  w.vm.open = true; await flushPromises(); await prepare(dialog, '00042')
  await dialog.find('[data-testid="physical-confirm"]').trigger('click'); await flushPromises()
  expect(requests).toHaveLength(2); expect(requests[1].card_uid).toBe('00042')
  expect(requests[1].idempotency_key).not.toBe(requests[0].idempotency_key)
})
