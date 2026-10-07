import { expect, test } from 'vitest'
import { ResetWorkflow } from './reset'
const state = { period_id: 'p1', business_revision: 1, policy_version: 1, maintenance: false, owner_reset_allowed: true }
const preview = { state, confirmation_token: 'signed', expires_at: new Date(Date.now() + 300000).toISOString(), summary: { members: 2, stored_balance: '50.00', remaining_passes: 3, active_visits: 1, unsettled_amount: '20.00', stock_items: 1, stock_quantity: '4' } }
const task = { id: 't1', idempotency_key: 'query-1', status: 'queued', stage: 'queued', old_period_id: 'p1' }
test.each(['failed', 'completed'])('terminal task A (%s) cannot unlock task C while task B is unconfirmed', async status => {
  let saved = ''; let keys = 0; let posts = 0
  const flow = new ResetWorkflow({
    request: async (method, path) => {
      if (path.endsWith('preview')) return preview
      if (method === 'POST') { posts++; if (posts === 1) return { ...task, idempotency_key: 'query-1', status }; throw new Error('lost create') }
      throw new Error('query unavailable')
    },
    capture: () => 1, isCurrent: () => true, clear: () => undefined,
    readKey: () => saved, saveKey: key => { saved = key }, createKey: () => `query-${++keys}`, now: () => Date.now(),
  })
  await flow.loadPreview(); await flow.submit('owner', 'secret', '重置当前经营数据')
  await flow.loadPreview(); await flow.submit('owner', 'secret', '重置当前经营数据')
  expect(saved).toBe('query-2')
  await flow.loadPreview(); await flow.submit('owner', 'secret', '重置当前经营数据')
  expect(posts).toBe(2)
  expect(saved).toBe('query-2')
  expect(flow.preview).toBeNull()
})
function setup(request: (...args: any[]) => Promise<any>) {
  let key = ''; let generation = 1
  const flow = new ResetWorkflow({ request, capture: () => generation, isCurrent: (value: number) => value === generation, clear: () => { generation++ }, readKey: () => key, saveKey: (value: string) => { key = value }, createKey: () => 'query-1', now: () => Date.now() })
  return { flow, key: () => key, invalidate: () => { generation++ } }
}
test('preview displays real amounts and duplicate submit sends one saved query key', async () => {
  const calls: any[] = []; let finish!: () => void
  const { flow, key } = setup(async (method, path, body) => {
    calls.push({ method, path, body })
    if (path.endsWith('preview')) return preview
    expect(key()).toBe('query-1')
    return new Promise(resolve => { finish = () => resolve(task) })
  })
  await flow.loadPreview()
  expect(flow.preview?.summary.stored_balance).toBe('50.00')
  const first = flow.submit('owner', 'secret', '重置当前经营数据')
  await flow.submit('owner', 'secret', '重置当前经营数据')
  expect(calls).toHaveLength(2)
  expect(flow.preview).toBeNull()
  finish(); await first
  expect(flow.task?.status).toBe('queued')
})
test.each(['completed', 'failed'])('task recovery reports a known %s outcome without another POST', async status => {
  const { flow, key } = setup(async (method, path) => {
    if (path.endsWith('preview')) return preview
    if (method === 'POST') return task
    return [{ ...task, status, stage: status, message: '备份校验失败', error_code: 'RESET_BACKUP_FAILED' }]
  })
  await flow.loadPreview(); await flow.submit('owner', 'secret', '重置当前经营数据')
  await flow.recover()
  expect(flow.task?.status).toBe(status)
  expect(key()).toBe('query-1')
  expect(flow.message).toContain(status === 'completed' ? '已完成' : '备份校验失败')
})
test('a lost create and unavailable task query retains the identifier and unconfirmed result', async () => {
  let posts = 0
  const { flow, key } = setup(async (method, path) => {
    if (path.endsWith('preview')) return preview
    if (method === 'POST') posts++
    throw new Error('离线')
  })
  await flow.loadPreview(); await flow.submit('owner', 'secret', '重置当前经营数据')
  await flow.loadPreview()
  expect(posts).toBe(1)
  expect(key()).toBe('query-1')
  expect(flow.task).toBeNull()
  expect(flow.preview).toBeNull()
  expect(flow.message).toContain('先查询原任务结果')
})
test.each(['wrong text', 'expired', 'empty password'])('blocks invalid reset %s before network', async reason => {
  let posts = 0
  const { flow } = setup(async method => { if (method === 'POST') posts++; return preview })
  await flow.loadPreview()
  if (reason === 'expired') flow.preview = { ...preview, expires_at: new Date(0).toISOString() }
  await flow.submit('owner', reason === 'empty password' ? '' : 'secret', reason === 'wrong text' ? '重置' : '重置当前经营数据')
  expect(posts).toBe(0)
  expect(flow.message).not.toBe('')
})
test('a lost create response recovers by the saved identifier without another destructive POST', async () => {
  let posts = 0
  const { flow, key } = setup(async (method, path, _body, params) => {
    if (path.endsWith('preview')) return preview
    if (method === 'POST') { posts++; throw new Error('lost response') }
    expect(params).toEqual({ idempotency_key: 'query-1' })
    return [task]
  })
  await flow.loadPreview(); await flow.submit('owner', 'secret', '重置当前经营数据')
  expect(key()).toBe('query-1')
  expect(flow.task?.id).toBe('t1')
  expect(posts).toBe(1)
})
test('late old preview and error cannot mutate a replacement workflow state', async () => {
  let reject!: (error: Error) => void
  const { flow, invalidate } = setup(() => new Promise((_resolve, fail) => { reject = fail }))
  const pending = flow.loadPreview()
  expect(typeof reject).toBe('function')
  invalidate(); flow.message = 'new'; flow.busy = true
  reject(new Error('old error')); await pending
  expect(flow.message).toBe('new')
  expect(flow.busy).toBe(true)
})
test('archive evidence uses bounded pages and preserves decimal strings', async () => {
  const { flow } = setup(async (_method, path, _body, params) => {
    expect(path).toBe('/business/archives/p-old/evidence')
    expect(params).toEqual({ table: 'members', page: 2, page_size: 100 })
    return { period_id: 'p-old', table: 'members', page: 2, has_more: true, rows: [{ balance: '10.01' }] }
  })
  await flow.loadEvidence('p-old', 'members', 2)
  expect(flow.evidence?.rows[0].balance).toBe('10.01')
})
test('a confirmed wrong password releases the uncreated task key for a fresh preview', async () => {
  const { flow, key } = setup(async (method) => {
    if (method === 'POST') throw { response: { data: { error: { code: 'REAUTH_FAILED' }, message: '账号或密码错误' } } }
    return preview
  })
  await flow.loadPreview(); await flow.submit('owner', 'bad', '重置当前经营数据')
  expect(key()).toBe('')
  expect(flow.message).toContain('密码')
  await flow.loadPreview()
  expect(flow.preview?.confirmation_token).toBe('signed')
})
