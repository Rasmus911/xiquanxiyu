import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, expect, it } from 'vitest'
import { http } from '../../api/http'
import { clearBusinessSession } from '../../business/state'
import CardScanDialog from './CardScanDialog.vue'
import MemberCardBindingDialog from './MemberCardBindingDialog.vue'

const member = { id: 'member-1', phone: '', name: '', balance: '125.50', is_active: true, holder_surname: null,
  card_binding: { id: 'binding-1', member_id: 'member-1', card_uid: '000315346091', is_active: true, created_at: '2026-10-12T00:00:00Z', revoked_at: null, replaced_by_id: null, version: 1 } }
const boundMember = { ...member, card_binding: { ...member.card_binding, card_uid: '000123' } }
const bindingResult = { member: boundMember, card_binding: boundMember.card_binding }
let cleanup = () => {}
const originalAdapter = http.defaults.adapter
afterEach(() => { cleanup(); clearBusinessSession(); http.defaults.adapter = originalAdapter; localStorage.clear(); sessionStorage.clear() })
it('binds or replaces only after current operator password and clears secrets on failure/retry/success', async () => {
  const pinia = createPinia(); setActivePinia(pinia)
  const requests: any[] = []
  http.defaults.adapter = async config => { requests.push({ url: config.url, body: JSON.parse(config.data) }); if (requests.length === 1) throw new Error('密码验证失败'); return { config, status: 200, statusText: '', headers: {}, data: { data: bindingResult } } }
  const w = mount(MemberCardBindingDialog, { props: { modelValue: true, member }, global: { plugins: [ElementPlus, pinia], stubs: { teleport: true } } }); cleanup = () => w.unmount(); await flushPromises()
  expect(w.text()).toContain('补办实体卡'); await w.find('[data-testid="binding-scan"]').trigger('click'); await flushPromises()
  const input = w.findComponent(CardScanDialog).find('input'); await input.setValue('000123'); await input.trigger('keydown', { key: 'Enter' }); await flushPromises()
  await w.find('[data-testid="binding-confirm"]').trigger('click'); await flushPromises(); expect(requests).toHaveLength(0)
  await w.find('[name="password"]').setValue('fixture-operator-password'); await w.find('[data-testid="binding-confirm"]').trigger('click'); await flushPromises()
  expect(requests[0]).toMatchObject({ url: '/members/member-1/physical-card', body: { card_uid: '000123', password: 'fixture-operator-password' } })
  expect((w.find('[name="password"]').element as HTMLInputElement).value).toBe('')
  expect([...Object.values(localStorage), ...Object.values(sessionStorage)].join('')).not.toContain('fixture-operator-password')
  await w.find('[name="password"]').setValue('fixture-operator-password'); await w.find('[data-testid="binding-confirm"]').trigger('click'); await flushPromises()
  expect(requests[1].body.idempotency_key).toBe(requests[0].body.idempotency_key); expect(w.emitted('bound')).toEqual([[boundMember]])
  expect((w.find('[name="password"]').element as HTMLInputElement).value).toBe('')
})
it.each(['close', 'header', 'session', 'unmount', 'member'])('ignores stale binding result and clears password after %s', async action => {
  const pinia = createPinia(); setActivePinia(pinia); let resolve!: (value: any) => void
  http.defaults.adapter = config => new Promise(r => { resolve = data => r({ config, status: 200, statusText: '', headers: {}, data: { data } }) })
  const w = mount(MemberCardBindingDialog, { props: { modelValue: true, member }, global: { plugins: [ElementPlus, pinia], stubs: { teleport: true } } }); cleanup = () => w.unmount(); await flushPromises()
  await w.find('[data-testid="binding-scan"]').trigger('click'); await flushPromises(); const input = w.findComponent(CardScanDialog).find('input')
  await input.setValue('000123'); await input.trigger('keydown', { key: 'Enter' }); await flushPromises()
  await w.find('[name="password"]').setValue('fixture-secret'); await w.find('[data-testid="binding-confirm"]').trigger('click'); await flushPromises()
  if (action === 'close') { await w.setProps({ modelValue: false }); await w.setProps({ modelValue: true }) }
  else if (action === 'header') (w.find('.el-dialog__headerbtn').element as HTMLButtonElement).click()
  else if (action === 'session') clearBusinessSession()
  else if (action === 'member') await w.setProps({ member: { ...member, id: 'member-2' } })
  else w.unmount()
  resolve(bindingResult); await flushPromises(); expect(w.emitted('bound')).toBeUndefined()
  if (action !== 'unmount') expect((w.find('[name="password"]').element as HTMLInputElement).value).toBe('')
})
