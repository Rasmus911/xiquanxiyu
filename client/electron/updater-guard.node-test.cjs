const test = require('node:test')
const assert = require('node:assert/strict')

const { installationDecision, normalizeBusyReason } = require('./updater-guard.cjs')

test('normalizes only meaningful string busy reasons', () => {
  assert.equal(normalizeBusyReason(' 正在确认收款 '), '正在确认收款')
  assert.equal(normalizeBusyReason('   '), null)
  assert.equal(normalizeBusyReason(null), null)
  assert.equal(normalizeBusyReason({ reason: '伪造对象' }), null)
})

test('blocks installation while a business write is running', () => {
  assert.deepEqual(installationDecision('downloaded', '正在确认收款'), {
    ok: false,
    reason: '正在确认收款',
  })
})

test('allows installation only after an update is downloaded and the app is idle', () => {
  assert.deepEqual(installationDecision('downloaded', null), { ok: true })
  assert.deepEqual(installationDecision('idle', null), {
    ok: false,
    reason: '更新尚未下载完成',
  })
})
