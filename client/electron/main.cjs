const { app, BrowserWindow, ipcMain, Menu, session, screen, dialog } = require('electron')
const { pathToFileURL } = require('node:url')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const updater = require('./updater.cjs')
const { toPrinterList } = require('./ipc-values.cjs')
const { isTrustedPage, isTrustedIpc, menuTemplate } = require('./security.cjs')
const { windowBounds, diagnostics, readRenderingPreference } = require('./compatibility.cjs')
const { receiptHtml } = require('./receipt.cjs')

let mainWindow
let trustedRendererUrl
let compatibilityRestarting = false
let renderingRecoveryPrompt = false
const compatibilityPath = path.join(app.getPath('userData'), 'desktop-compat.json')
let softwareRendering = false
try { softwareRendering = readRenderingPreference(fs.readFileSync(compatibilityPath, 'utf8')) } catch { /* First run. */ }
if (softwareRendering) app.disableHardwareAcceleration()
const primaryInstance = app.requestSingleInstanceLock()
if (!primaryInstance) app.quit()

function desktopDiagnostics() {
  return diagnostics({ profile: updater.getTargetIdentity(), versions: process.versions,
    osRelease: os.release(), softwareRendering })
}
function restartWithRendering(enabled) {
  if (typeof enabled !== 'boolean') return { ok: false, reason: '显示兼容设置无效' }
  const busy = updater.getState().businessBusyReason
  if (busy) return { ok: false, reason: `${busy}，完成后再重启` }
  fs.mkdirSync(path.dirname(compatibilityPath), { recursive: true })
  fs.writeFileSync(compatibilityPath, JSON.stringify({ softwareRendering: enabled }), 'utf8')
  setImmediate(() => {
    if (updater.getState().businessBusyReason) return
    compatibilityRestarting = true
    app.relaunch(); app.quit()
  })
  return { ok: true }
}

async function offerRenderingRecovery() {
  if (renderingRecoveryPrompt || !mainWindow || mainWindow.isDestroyed()) return
  renderingRecoveryPrompt = true
  try {
    const choice = await dialog.showMessageBox(mainWindow, {
      type: 'warning', title: '页面进程已停止',
      message: '页面已停止，可以在营业空闲时尝试软件渲染。',
      detail: '正在进行的付款请先查询结果，不要重复付款。重启不会清除终端设置，也不会重新提交交易。',
      buttons: ['使用软件渲染重新启动', '暂不重启'], defaultId: 1, cancelId: 1, noLink: true,
    })
    if (choice.response === 0) {
      const result = restartWithRendering(true)
      if (!result.ok) dialog.showErrorBox('暂时不能重启', result.reason)
    }
  } catch {
    dialog.showErrorBox('页面进程已停止', '请记录版本信息，在营业空闲时重新启动；付款结果请先查询，不要重复付款。')
  } finally { renderingRecoveryPrompt = false }
}

function registerIpc(channel, handler) {
  ipcMain.handle(channel, (event, ...args) => {
    if (!mainWindow || !isTrustedIpc(event, mainWindow.webContents.id, trustedRendererUrl)) {
      throw new Error('IPC_SENDER_NOT_TRUSTED')
    }
    return handler(event, ...args)
  })
}

function configPath() {
  return path.join(app.getPath('userData'), 'terminal-config.json')
}

function readConfig() {
  try {
    return JSON.parse(fs.readFileSync(configPath(), 'utf8'))
  } catch {
    return {}
  }
}

function writeConfig(value) {
  const safe = {
    serverUrl: String(value.serverUrl || ''),
    terminalCode: String(value.terminalCode || ''),
    terminalName: String(value.terminalName || ''),
    printerName: String(value.printerName || ''),
  }
  fs.mkdirSync(path.dirname(configPath()), { recursive: true })
  fs.writeFileSync(configPath(), JSON.stringify(safe, null, 2), 'utf8')
  updater.updateServerUrl(safe.serverUrl)
  return safe
}


function createWindow() {
  trustedRendererUrl = app.isPackaged
    ? pathToFileURL(path.join(__dirname, '..', 'dist', 'index.html')).href
    : 'http://127.0.0.1:5173/'
  mainWindow = new BrowserWindow({
    ...windowBounds(screen.getPrimaryDisplay().workAreaSize),
    show: false,
    backgroundColor: '#f3f6fa',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webviewTag: false,
    },
  })
  mainWindow.once('ready-to-show', () => {
    mainWindow.maximize()
    mainWindow.show()
  })
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!isTrustedPage(url, trustedRendererUrl)) event.preventDefault()
  })
  mainWindow.webContents.on('will-redirect', (event, url) => {
    if (!isTrustedPage(url, trustedRendererUrl)) event.preventDefault()
  })
  mainWindow.webContents.on('will-attach-webview', (event) => event.preventDefault())
  mainWindow.on('close', event => {
    if (updater.getState().businessBusyReason) {
      event.preventDefault()
      mainWindow.webContents.send('updater:state', updater.getState())
    }
  })
  mainWindow.webContents.on('render-process-gone', () => {
    void offerRenderingRecovery()
  })
  mainWindow.webContents.on('did-fail-load', (_event, code, _description, _url, isMainFrame) => {
    if (isMainFrame && code !== -3) dialog.showErrorBox('页面加载失败', '请确认安装完整，或重新覆盖安装对应系统版本。不要卸载或删除终端设置。')
  })
  mainWindow.on('closed', () => { mainWindow = null })
  if (!app.isPackaged) {
    mainWindow.loadURL('http://127.0.0.1:5173')
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  }
}

if (primaryInstance) app.whenReady().then(() => {
  const startupError = updater.getStartupError()
  if (startupError) { dialog.showErrorBox('安装版本不匹配', startupError); app.quit(); return }
  if (process.argv.includes('--compat-smoke')) {
    console.log(JSON.stringify({ compatibilitySmoke: true, ...desktopDiagnostics() }))
    app.exit(0)
    return
  }
  app.setAppUserModelId('com.xiquan.bathhouse')
  Menu.setApplicationMenu(Menu.buildFromTemplate(menuTemplate(!app.isPackaged)))
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
  session.defaultSession.setPermissionCheckHandler(() => false)
  registerIpc('config:get', () => readConfig())
  registerIpc('config:set', (_event, config) => writeConfig(config || {}))
  registerIpc('desktop:diagnostics', () => desktopDiagnostics())
  registerIpc('desktop:software-rendering', (_event, enabled) => restartWithRendering(enabled))
  registerIpc('updater:get-state', () => updater.getState())
  registerIpc('updater:check', () => updater.checkForUpdates())
  registerIpc('updater:install', () => updater.installUpdate())
  registerIpc('updater:set-business-busy', (_event, reason) => {
    const safeReason = typeof reason === 'string' ? reason : null
    return updater.setBusinessBusy(safeReason)
  })
  registerIpc('printer:list', async () => {
    if (!mainWindow) return []
    return toPrinterList(await mainWindow.webContents.getPrintersAsync())
  })
  registerIpc('printer:receipt', async (_event, receipt, printerName) => {
    const printWindow = new BrowserWindow({
      show: false,
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
    })
    try {
      await printWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(receiptHtml(receipt || {}))}`)
      return await new Promise((resolve) => {
        printWindow.webContents.print(
          {
            silent: true,
            deviceName: printerName || undefined,
            printBackground: true,
            usePrinterDefaultPageSize: true,
          },
          (success, failureReason) => resolve({ success, error: failureReason || undefined }),
        )
      })
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    } finally {
      printWindow.destroy()
    }
  })
  createWindow()
  updater.start(readConfig().serverUrl, () => mainWindow)
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('second-instance', () => {
  if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.show(); mainWindow.focus() }
})
app.on('before-quit', event => {
  if (!compatibilityRestarting) updater.onBeforeQuit(event)
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
