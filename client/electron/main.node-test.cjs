const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const vm = require('node:vm')
const { EventEmitter } = require('node:events')

async function fixture({ software = false, lock = true, startupError = '', renderResponse = 1 } = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'xiquan-main-'))
  if (software) fs.writeFileSync(path.join(directory, 'desktop-compat.json'), '{"softwareRendering":true}')
  const calls = [], handlers = new Map(), windows = []
  const app = Object.assign(new EventEmitter(), {
    isPackaged: false, getPath: () => directory, getVersion: () => '0.4.2',
    requestSingleInstanceLock: () => lock, whenReady: () => Promise.resolve(),
    setAppUserModelId() {}, disableHardwareAcceleration: () => calls.push('software'),
    relaunch: () => calls.push('relaunch'), quit: () => calls.push('quit'), exit: () => calls.push('exit'),
  })
  class BrowserWindow extends EventEmitter {
    constructor(options) {
      super(); this.options = options; this.webContents = Object.assign(new EventEmitter(), {
        id: windows.length + 1, setWindowOpenHandler() {}, send() {}, print(_options, callback) { callback(true) },
        getPrintersAsync: async () => [{ name: 'XP-58', displayName: 'XP-58', status: 0 }],
      }); windows.push(this)
    }
    loadURL() { return Promise.resolve() } loadFile() { return Promise.resolve() }
    maximize() { calls.push(`maximize:${windows.indexOf(this)}`) }
    show() { calls.push(`show:${windows.indexOf(this)}`) } destroy() {} focus() { calls.push('focus') } isMinimized() { return false } isDestroyed() { return false }
    static getAllWindows() { return windows }
  }
  let busy = null
  const updater = {
    start() {}, updateServerUrl() {}, getStartupError: () => startupError,
    getTargetIdentity: () => ({ targetId: 'win10-x64', arch: 'x64', buildId: 'fixture', releaseTrust: { testOnly: true } }),
    getState: () => ({ businessBusyReason: busy }), setBusinessBusy: value => { busy = value; return { businessBusyReason: busy } },
    checkForUpdates() {}, installUpdate() {}, onBeforeQuit: () => calls.push('quit-guard'),
  }
  const electron = { app, BrowserWindow, ipcMain: { handle: (channel, handler) => handlers.set(channel, handler) },
    Menu: { buildFromTemplate: value => value, setApplicationMenu() {} },
    session: { defaultSession: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} } },
    screen: { getPrimaryDisplay: () => ({ workAreaSize: { width: 819, height: 580 } }) },
    dialog: { showErrorBox: () => calls.push('error-dialog'), showMessageBox: async () => {
      calls.push('rendering-dialog'); return { response: renderResponse }
    } },
  }
  const context = { require: name => name === 'electron' ? electron : name === './updater.cjs' ? updater : require(name),
    __dirname, process: { platform: 'win32', arch: 'x64', argv: [], versions: { electron: '44.5.1', chrome: '152', node: '24' } }, console, setImmediate }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'main.cjs'), 'utf8'), context, { filename: 'main.cjs' })
  await new Promise(resolve => setImmediate(resolve))
  const event = { sender: { id: 1 }, senderFrame: { url: 'http://127.0.0.1:5173/', parent: null } }
  return { app, calls, windows, handlers, event, directory, close: () => fs.rmSync(directory, { recursive: true, force: true }) }
}

test('real main keeps the sandbox and scaled bounds, and diagnostics only accept the trusted top-level renderer', async () => {
  const f = await fixture({ software: true })
  try {
    assert.ok(f.calls.includes('software'))
    const win = f.windows[0]
    assert.equal(win.options.width, 819); assert.equal(win.options.height, 580)
    assert.equal(win.options.webPreferences.sandbox, true)
    const handler = f.handlers.get('desktop:diagnostics')
    assert.equal(handler(f.event).softwareRendering, true)
    assert.throws(() => handler({ ...f.event, sender: { id: 999 } }), /NOT_TRUSTED/)
    assert.throws(() => handler({ ...f.event, senderFrame: { ...f.event.senderFrame, parent: {} } }), /NOT_TRUSTED/)
    assert.equal(JSON.stringify(handler(f.event)).includes('serverUrl'), false)
    const printers = await f.handlers.get('printer:list')(f.event)
    assert.equal(printers[0].name, 'XP-58')
  } finally { f.close() }
})

test('busy operations block window close and rendering restart without writing preferences', async () => {
  const f = await fixture()
  try {
    f.handlers.get('updater:set-business-busy')(f.event, '正在充值')
    let prevented = false
    f.windows[0].emit('close', { preventDefault: () => { prevented = true } })
    assert.equal(prevented, true)
    assert.equal((await f.handlers.get('desktop:software-rendering')(f.event, true)).ok, false)
    assert.equal(fs.existsSync(path.join(f.directory, 'desktop-compat.json')), false)
    f.handlers.get('updater:set-business-busy')(f.event, null)
    assert.equal((await f.handlers.get('desktop:software-rendering')(f.event, true)).ok, true)
    await new Promise(resolve => setImmediate(resolve))
    assert.ok(f.calls.includes('relaunch')); assert.ok(f.calls.includes('quit'))
    appEvent(f.app)
    assert.equal(f.calls.includes('quit-guard'), false, 'rendering restart cannot also install an update')
  } finally { f.close() }
})
function appEvent(app) { app.emit('before-quit', { preventDefault() {} }) }

test('main maximizes before showing once while receipt windows remain hidden', async () => {
  const f=await fixture()
  try {
    assert.equal(f.calls.some(value=>value.startsWith('maximize:')),false)
    f.windows[0].emit('ready-to-show');f.windows[0].emit('ready-to-show')
    assert.deepEqual(f.calls.filter(value=>/^(maximize|show):/.test(value)),['maximize:0','show:0'])
    await f.handlers.get('printer:receipt')(f.event,{},'XP-58')
    f.windows[1].emit('ready-to-show')
    assert.equal(f.windows[1].options.show,false)
    assert.deepEqual(f.calls.filter(value=>/^(maximize|show):/.test(value)),['maximize:0','show:0'])
  } finally {f.close()}
})

test('duplicate instances and invalid packaged identities do not open business windows', async () => {
  for (const options of [{ lock: false }, { startupError: '安装目标无效' }]) {
    const f = await fixture(options)
    try { assert.equal(f.windows.length, 0); assert.ok(f.calls.includes('quit')) }
    finally { f.close() }
  }
})

test('a rendering restart rechecks business activity before exiting', async () => {
  const f = await fixture()
  try {
    assert.equal(f.handlers.get('desktop:software-rendering')(f.event, true).ok, true)
    f.handlers.get('updater:set-business-busy')(f.event, '正在结账')
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(f.calls.includes('relaunch'), false)
    assert.equal(f.calls.includes('quit'), false)
  } finally { f.close() }
})

test('a renderer failure offers native recovery but only explicit idle confirmation can restart', async () => {
  for (const [renderResponse, busy, shouldRestart] of [[1, null, false], [0, '正在结账', false], [0, null, true]]) {
    const f = await fixture({ renderResponse })
    try {
      f.handlers.get('updater:set-business-busy')(f.event, busy)
      f.windows[0].webContents.emit('render-process-gone')
      await new Promise(resolve => setImmediate(resolve))
      await new Promise(resolve => setImmediate(resolve))
      assert.ok(f.calls.includes('rendering-dialog'))
      assert.equal(f.calls.includes('relaunch'), shouldRestart)
      assert.equal(fs.existsSync(path.join(f.directory, 'desktop-compat.json')), shouldRestart)
    } finally { f.close() }
  }
})
