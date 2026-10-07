const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

test('sandboxed preload does not require local modules', () => {
  const source = fs.readFileSync(path.join(__dirname, 'preload.cjs'), 'utf8')

  assert.doesNotMatch(source, /require\s*\(\s*['"]\./)
  assert.match(source, /contextBridge\.exposeInMainWorld\(['"]xiquan['"]/)
  assert.match(source, /setBusinessBusy/)
})

test('real sandbox preload exposes diagnostics and boolean-only rendering preference IPC', async () => {
  const calls = []
  let bridge
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'preload.cjs'), 'utf8'), {
    require: name => {
      assert.equal(name, 'electron')
      return { contextBridge: { exposeInMainWorld: (_name, value) => { bridge = value } },
        ipcRenderer: { invoke: async (...args) => { calls.push(args); return { ok: true } }, on() {}, removeListener() {} } }
    },
  })
  await bridge.getDesktopDiagnostics()
  await bridge.restartWithSoftwareRendering('true')
  assert.deepEqual(calls, [['desktop:diagnostics'], ['desktop:software-rendering', false]])
})
