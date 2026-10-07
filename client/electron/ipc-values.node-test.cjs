const assert = require('node:assert/strict')
const test = require('node:test')
const { toPrinterList, toTerminalConfig } = require('./ipc-values.cjs')

test('Vue-style proxy is converted to an IPC-cloneable terminal config', () => {
  const reactiveLikeConfig = new Proxy({
    serverUrl: 'https://api.example.com/api',
    terminalCode: 'FRONT-01',
    terminalName: '前台主机',
  }, {})

  assert.throws(() => structuredClone(reactiveLikeConfig), { name: 'DataCloneError' })

  const safeConfig = toTerminalConfig(reactiveLikeConfig)
  assert.deepEqual(structuredClone(safeConfig), {
    serverUrl: 'https://api.example.com/api',
    terminalCode: 'FRONT-01',
    terminalName: '前台主机',
    printerName: '',
  })
})

test('Electron printer objects are reduced to clone-safe display data', () => {
  const printers = toPrinterList([
    { name: 'Microsoft Print to PDF', displayName: 'PDF', isDefault: false, options: new Proxy({}, {}) },
    { name: 'XP-58', displayName: '', description: 'USB003', status: 0, isDefault: true },
  ])

  assert.deepEqual(structuredClone(printers), [
    { name: 'XP-58', displayName: 'XP-58', description: 'USB003', status: 0, isDefault: true },
    { name: 'Microsoft Print to PDF', displayName: 'PDF', description: '', status: 0, isDefault: false },
  ])
})
