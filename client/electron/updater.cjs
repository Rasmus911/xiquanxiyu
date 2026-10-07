const { app, Notification } = require('electron')
const { autoUpdater } = require('electron-updater')
const { ElectronHttpExecutor } = require('electron-updater/out/electronHttpExecutor')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { assertPackagedTarget } = require('./target-profiles.cjs')
const { deriveTargetUrls } = require('./update-url.cjs')
const { requestHttpsJson, requestHttpsBuffer } = require('./https-json.cjs')
const { verifySignedRelease, verifyDownloadedArtifact, sha256 } = require('./desktop-release.cjs')
const { createPinnedExecutorClass } = require('./update-executor.cjs')
const { createUpdaterController } = require('./updater-controller.cjs')

let windowProvider = () => null
let identity = null
let startupError = ''
let scheduled = false
if (app.isPackaged) {
  try {
    identity = assertPackagedTarget(require('../package.json').xiquanDesktop, {
      platform: process.platform, arch: process.arch, release: os.release(),
      electronVersion: process.versions.electron,
    })
  } catch (error) { startupError = String(error.message || '桌面安装包身份无效，请重新安装对应系统版本') }
}
const enabled = Boolean(identity && !identity.releaseTrust.testOnly && !startupError)
const urls = identity ? deriveTargetUrls('https://api.pqxqxy.xyz/api', identity.targetId) : null
const cacheFile = identity ? path.join(app.getPath('userData'), `desktop-update-state-${identity.targetId}.json`) : null

function readSequence() {
  try {
    const value = JSON.parse(fs.readFileSync(cacheFile, 'utf8'))
    if (Number.isSafeInteger(value.sequence) && value.sequence > 0 && /^[0-9a-f]{64}$/.test(value.payloadHash)) return value
  } catch { /* A missing cache is expected on first installation. */ }
  return { sequence: 0, payloadHash: '' }
}

async function loadRelease() {
  const cache = readSequence()
  const envelope = await requestHttpsJson(urls.policyUrl, { allowedOrigin: urls.origin })
  const release = verifySignedRelease(envelope, {
    trust: identity.releaseTrust, profile: identity, currentVersion: app.getVersion(),
    lastSequence: cache.sequence, lastPayloadHash: cache.payloadHash,
  })
  const yaml = await requestHttpsBuffer(`${urls.feedUrl}latest.yml`, { allowedOrigin: urls.origin })
  if (sha256(yaml) !== release.updaterManifest.sha256) throw new Error('更新清单校验失败')
  fs.mkdirSync(path.dirname(cacheFile), { recursive: true })
  fs.writeFileSync(`${cacheFile}.new`, JSON.stringify({ sequence: release.sequence, payloadHash: release.payloadHash }), 'utf8')
  fs.renameSync(`${cacheFile}.new`, cacheFile)
  return release
}

const controller = createUpdaterController({
  updater: autoUpdater,
  app: { isPackaged: enabled, getVersion: () => app.getVersion() },
  loadRelease,
  verifyArtifact: verifyDownloadedArtifact,
  emit: state => {
    const win = windowProvider()
    if (win && !win.isDestroyed()) win.webContents.send('updater:state', state)
  },
  notify: version => {
    if (Notification.isSupported()) new Notification({
      title: '溪泉洗浴管理系统有新版本',
      body: `版本 ${version} 已验证，营业空闲时可覆盖安装。`,
    }).show()
  },
})
if (enabled) {
  const PinnedExecutor = createPinnedExecutorClass(ElectronHttpExecutor)
  autoUpdater.httpExecutor = new PinnedExecutor({ origin: urls.origin, feedPath: new URL(urls.feedUrl).pathname })
  autoUpdater.setFeedURL({ provider: 'generic', url: urls.feedUrl })
}

function getState() {
  const state = controller.getState()
  if (startupError) return { ...state, status: 'error', message: startupError }
  if (identity?.releaseTrust.testOnly) return { ...state, status: 'disabled', message: '兼容测试候选包，未开启正式自动更新' }
  return state
}
async function checkForUpdates() {
  if (enabled) await controller.checkForUpdates()
  return getState()
}
function start(_serverUrl, provider) {
  windowProvider = provider || windowProvider
  if (!enabled || scheduled || process.argv?.includes('--compat-smoke')) return
  scheduled = true
  setTimeout(() => { void checkForUpdates() }, 15_000).unref?.()
  setInterval(() => { void checkForUpdates() }, 6 * 60 * 60 * 1000).unref?.()
}

module.exports = {
  start, getState, checkForUpdates,
  // Server/terminal settings never switch a packaged update channel or trust anchor.
  updateServerUrl: () => getState(),
  installUpdate: () => controller.installUpdate(),
  setBusinessBusy: reason => { controller.setBusinessBusy(reason); return getState() },
  onBeforeQuit: event => controller.onBeforeQuit(event),
  getTargetIdentity: () => identity,
  getStartupError: () => startupError,
}

