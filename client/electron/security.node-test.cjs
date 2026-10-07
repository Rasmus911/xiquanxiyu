const { test } = require('node:test')
const assert = require('node:assert/strict')
const { isTrustedPage, isTrustedIpc, menuTemplate } = require('./security.cjs')

test('packaged renderer cannot navigate to a remote page or another local file', () => {
  const expected = 'file:///F:/app/dist/index.html'
  assert.equal(isTrustedPage(`${expected}#/checkout`, expected), true)
  assert.equal(isTrustedPage('https://evil.example', expected), false)
  assert.equal(isTrustedPage('file:///F:/app/other.html', expected), false)
})

test('IPC accepts only the configured main renderer frame', () => {
  const expected = 'file:///F:/app/dist/index.html'
  assert.equal(isTrustedIpc({ sender: { id: 3 }, senderFrame: { url: expected, parent: null } }, 3, expected), true)
  assert.equal(isTrustedIpc({ sender: { id: 4 }, senderFrame: { url: expected, parent: null } }, 3, expected), false)
  assert.equal(isTrustedIpc({ sender: { id: 3 }, senderFrame: { url: 'https://evil.example', parent: null } }, 3, expected), false)
})

test('native editing commands remain available and production does not expose reload or developer tools', () => {
  const roles = menuTemplate(false).flatMap(item => item.submenu || []).map(item => item.role)
  for (const role of ['copy', 'paste', 'cut', 'undo', 'redo', 'selectAll']) assert.ok(roles.includes(role))
  assert.ok(!roles.includes('toggleDevTools'))
  assert.ok(!roles.includes('reload'))
})
