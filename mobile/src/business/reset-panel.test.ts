// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { createApp, nextTick, type App } from 'vue'
import Panel from '../components/profile/BusinessResetPanel.vue'
import { http } from '../api'
import { acceptBusinessState, clearBusinessSession } from './state'
const state = { period_id: 'p1', policy_version: 1, business_revision: 1, maintenance: false, owner_reset_allowed: true }
let app: App; let host: HTMLDivElement
beforeEach(() => { localStorage.clear(); clearBusinessSession(); host = document.createElement('div'); document.body.append(host); app = createApp(Panel); app.mount(host) })
afterEach(() => { app.unmount(); host.remove() })
test('mobile panel polls an uncertain new key instead of trusting a previous failed task', async () => {
  vi.useFakeTimers()
  localStorage.setItem('xiquan_reset_query', 'query-A')
  let queries = 0; let posts = 0; let previews = 0
  http.defaults.adapter = async config => {
    let data: unknown
    if (config.url?.endsWith('preview')) { previews++; data = { state, confirmation_token: 'signed', expires_at: new Date(Date.now() + 300000).toISOString(), summary: { members: 2, stored_balance: '50.01', remaining_passes: 3, active_visits: 1, unsettled_amount: '20.00', stock_items: 1, stock_quantity: '4' } } }
    else if (config.method === 'post') { posts++; throw new Error('lost create') }
    else { queries++; if (config.params.idempotency_key !== 'query-A') throw new Error('lost query'); data = [{ id: 'task-A', idempotency_key: 'query-A', old_period_id: 'older-period', status: 'failed', stage: 'failed' }] }
    return { config, headers: {}, status: 200, statusText: '', data: { data } }
  }
  try {
    app.unmount()
    acceptBusinessState(state, ['business:reset']); await nextTick()
    app = createApp(Panel); app.mount(host)
    await vi.advanceTimersByTimeAsync(0); await nextTick()
    expect(queries).toBe(1)
    ;(host.querySelector('[data-preview]') as HTMLButtonElement).click(); await vi.advanceTimersByTimeAsync(0); await nextTick()
    for (const [name, value] of [['username', 'owner'], ['password', 'secret'], ['confirmation', '重置当前经营数据']]) {
      const input = host.querySelector(`[name="${name}"]`) as HTMLInputElement; input.value = value!; input.dispatchEvent(new Event('input'))
    }
    host.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true })); await vi.advanceTimersByTimeAsync(0); await nextTick()
    expect(posts).toBe(1)
    const key = localStorage.getItem('xiquan_reset_query'); const before = queries
    await vi.advanceTimersByTimeAsync(3000); await nextTick()
    expect(queries).toBeGreaterThan(before)
    ;(host.querySelector('[data-preview]') as HTMLButtonElement).click(); await vi.advanceTimersByTimeAsync(0)
    expect(previews).toBe(1); expect(posts).toBe(1); expect(localStorage.getItem('xiquan_reset_query')).toBe(key)
  } finally { vi.useRealTimers() }
})
test('mobile owner state exposes reset and archive while non-owner wildcard does not', async () => {
  expect(host.querySelector('[data-reset-panel]')).toBeNull()
  acceptBusinessState({ ...state, owner_reset_allowed: false }, ['*']); await nextTick()
  expect(host.querySelector('[data-reset-panel]')).toBeNull()
  acceptBusinessState(state, ['business:reset', 'business:archive']); await nextTick()
  expect(host.querySelector('[data-reset-panel]')).not.toBeNull()
  expect(host.querySelector('[data-archives]')).not.toBeNull()
})
test('mobile history continues evidence pages through the production transport', async () => {
  const requests: any[] = []
  http.defaults.adapter = async config => {
    requests.push({ url: config.url, params: config.params })
    const data = config.url === '/business/archives' ? [{ period_id: 'old', closed_at: '昨日', summary: {} }] : { period_id: 'old', table: 'members', page: config.params.page, has_more: config.params.page === 1, rows: [{ balance: '10.01' }] }
    return { config, headers: {}, status: 200, statusText: '', data: { data } }
  }
  acceptBusinessState(state, ['business:archive']); await nextTick()
  const click = async (label: string) => { const button = [...host.querySelectorAll('button')].find(row => row.textContent?.includes(label))!; button.click(); await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
  await click('查询历史归档'); await click('昨日'); await click('下一页证据')
  expect(host.textContent).toContain('证据第 2 页')
  expect(requests.at(-1)).toEqual({ url: '/business/archives/old/evidence', params: { table: 'members', page: 2, page_size: 100 } })
  expect(([...host.querySelectorAll('button')].find(row => row.textContent === '下一页证据') as HTMLButtonElement).disabled).toBe(true)
})
test('mobile preview displays server balance and explicit bounded history controls', async () => {
  http.defaults.adapter = async config => ({ config, headers: {}, status: 200, statusText: '', data: { data: { state, confirmation_token: 'signed', expires_at: new Date(Date.now() + 300000).toISOString(), summary: { members: 2, stored_balance: '80.25', remaining_passes: 1, active_visits: 1, unsettled_amount: '20.00', stock_items: 1, stock_quantity: '3' } } } })
  acceptBusinessState(state, ['business:reset']); await nextTick()
  expect(host.querySelector('[data-preview]')).not.toBeNull()
  ;(host.querySelector('[data-preview]') as HTMLButtonElement).click()
  await new Promise(resolve => setTimeout(resolve, 0)); await nextTick()
  expect(host.textContent).toContain('80.25')
  expect(host.textContent).toContain('5分钟')
})
