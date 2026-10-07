import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import Panel from '../components/settings/BusinessResetPanel.vue'
import { http } from '../api/http'
import { acceptBusinessState, clearBusinessSession } from './state'
import { AxiosError } from 'axios'
const state = { period_id: 'p1', policy_version: 1, business_revision: 2, maintenance: false, owner_reset_allowed: true }
let wrapper: ReturnType<typeof mount>
beforeEach(() => { localStorage.clear(); clearBusinessSession() })
afterEach(() => wrapper?.unmount())
test.each(['failed', 'completed'])('panel keeps polling task B after terminal task A (%s) and lost responses', async status => {
  vi.useFakeTimers()
  let posts = 0; let queries = 0; let previews = 0
  localStorage.setItem('xiquan_reset_query', 'query-A')
  http.defaults.adapter = async config => {
    let data: unknown
    if (config.url?.endsWith('preview')) { previews++; data = { state, confirmation_token: 'signed', expires_at: new Date(Date.now() + 300000).toISOString(), summary: { members: 2, stored_balance: '50.01', remaining_passes: 3, active_visits: 1, unsettled_amount: '20.00', stock_items: 1, stock_quantity: '4' } } }
    else if (config.method === 'post') { posts++; throw new Error('lost create') }
    else { queries++; if (config.params.idempotency_key !== 'query-A') throw new Error('lost query'); data = [{ id: 'task-A', idempotency_key: 'query-A', old_period_id: 'older-period', status, stage: status }] }
    return { config, headers: {}, status: 200, statusText: '', data: { data } }
  }
  acceptBusinessState(state, ['*']); wrapper = mount(Panel)
  try {
    await flushPromises()
    await wrapper.find('[data-preview]').trigger('click'); await flushPromises()
    await wrapper.find('[name="username"]').setValue('owner'); await wrapper.find('[name="password"]').setValue('secret'); await wrapper.find('[name="confirmation"]').setValue('重置当前经营数据')
    await wrapper.find('form').trigger('submit'); await flushPromises()
    const keyB = localStorage.getItem('xiquan_reset_query')
    const before = queries
    await vi.advanceTimersByTimeAsync(3000); await flushPromises()
    expect(queries).toBeGreaterThan(before)
    await wrapper.find('[data-preview]').trigger('click'); await flushPromises()
    expect(previews).toBe(1)
    expect(posts).toBe(1)
    expect(localStorage.getItem('xiquan_reset_query')).toBe(keyB)
  } finally { vi.useRealTimers() }
})
test('only authoritative owner state exposes the danger section', async () => {
  wrapper = mount(Panel)
  expect(wrapper.find('[data-reset-panel]').exists()).toBe(false)
  acceptBusinessState({ ...state, owner_reset_allowed: false }, ['*'])
  await wrapper.vm.$nextTick()
  expect(wrapper.find('[data-reset-panel]').exists()).toBe(false)
  acceptBusinessState(state, ['*']); await wrapper.vm.$nextTick()
  expect(wrapper.find('[data-reset-panel]').exists()).toBe(true)
})
test('archive continuation exports exactly the received evidence page without private downloads', async () => {
  const paths: Array<{ path: string; params: any }> = []
  http.defaults.adapter = async config => {
    paths.push({ path: String(config.url), params: config.params })
    const data = config.url === '/business/archives' ? [{ period_id: 'old', closed_at: '昨日', summary: { stored_balance: '10.01' } }] : { period_id: 'old', table: 'members', page: config.params.page, has_more: config.params.page === 1, rows: [{ balance: config.params.page === 1 ? '10.01' : '20.02' }] }
    return { config, headers: {}, status: 200, statusText: '', data: { data } }
  }
  acceptBusinessState(state, ['*']); wrapper = mount(Panel)
  await wrapper.find('[data-archives]').trigger('click'); await flushPromises()
  const click = async (text: string) => { await wrapper.findAll('button').find(row => row.text().includes(text))!.trigger('click'); await flushPromises() }
  await click('昨日'); await click('下一页证据')
  expect(wrapper.text()).toContain('证据第 2 页')
  expect(paths.at(-1)).toEqual({ path: '/business/archives/old/evidence', params: { table: 'members', page: 2, page_size: 100 } })
  let blob!: Blob
  const originalCreate = URL.createObjectURL; const originalRevoke = URL.revokeObjectURL
  URL.createObjectURL = (value: Blob | MediaSource) => { blob = value as Blob; return 'blob:page' }
  URL.revokeObjectURL = () => undefined
  const anchor = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  try {
    await click('导出当前页 JSON')
    const content = await new Promise<string>(resolve => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(blob) })
    expect(JSON.parse(content)).toEqual({ period_id: 'old', table: 'members', page: 2, has_more: false, rows: [{ balance: '20.02' }] })
    expect(content).not.toContain('10.01')
  } finally { anchor.mockRestore(); URL.createObjectURL = originalCreate; URL.revokeObjectURL = originalRevoke }
})
test('server owner denial is shown verbatim without manufacturing empty history', async () => {
  acceptBusinessState(state, ['*']); wrapper = mount(Panel)
  http.defaults.adapter = async config => { throw new AxiosError('denied', '', config, undefined, { config, headers: {}, status: 403, statusText: '', data: { success: false, message: '仅经营者可查询归档', error: { code: 'OWNER_REQUIRED', details: {} } } }) }
  await wrapper.find('[data-archives]').trigger('click'); await flushPromises()
  expect(wrapper.find('[role="status"]').text()).toBe('仅经营者可查询归档')
})
test('mounted panel shows preview values and removes submitted password immediately', async () => {
  let finish!: () => void; let submitted: any
  http.defaults.adapter = config => {
    const data = config.url?.endsWith('preview') ? { state, confirmation_token: 'signed', expires_at: new Date(Date.now() + 300000).toISOString(), summary: { members: 2, stored_balance: '50.01', remaining_passes: 3, active_visits: 1, unsettled_amount: '20.00', stock_items: 1, stock_quantity: '4' } } : null
    if (data) return Promise.resolve({ config, headers: {}, status: 200, statusText: '', data: { data } })
    submitted = JSON.parse(config.data)
    return new Promise(resolve => { finish = () => resolve({ config, headers: {}, status: 202, statusText: '', data: { data: { id: 't1', idempotency_key: submitted.idempotency_key, old_period_id: 'p1', status: 'queued', stage: 'queued' } } }) })
  }
  acceptBusinessState(state, ['*']); wrapper = mount(Panel)
  const preview = wrapper.find('[data-preview]')
  expect(preview.exists()).toBe(true)
  await preview.trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('50.01')
  await wrapper.find('[name="username"]').setValue('owner')
  await wrapper.find('[name="password"]').setValue('secret')
  await wrapper.find('[name="confirmation"]').setValue('重置当前经营数据')
  await wrapper.find('form').trigger('submit')
  expect((wrapper.find('[name="password"]').element as HTMLInputElement).value).toBe('')
  await flushPromises()
  expect(localStorage.getItem('xiquan_reset_query')).toBe(submitted.idempotency_key)
  expect((wrapper.find('[data-submit]').element as HTMLButtonElement).disabled).toBe(true)
  finish(); await flushPromises()
  expect(wrapper.text()).toContain('queued')
})
