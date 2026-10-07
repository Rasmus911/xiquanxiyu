const { assertUpdaterInfo } = require('./desktop-release.cjs')
const { decideDesktopUpdate } = require('./update-policy.cjs')
const { installationDecision, normalizeBusyReason } = require('./updater-guard.cjs')

function updateError(error) {
  const message = String(error?.message || '')
  if (message.includes('签名')) return '更新发布签名无效，已停止更新'
  if (message.includes('校验')) return '更新文件校验失败，已停止安装'
  if (message.includes('回退') || message.includes('冲突')) return '更新发布序号回退或冲突，已停止更新'
  if (message.includes('不匹配') || message.includes('清单')) return '更新目标或清单不匹配，已停止更新'
  if (message.includes('超时')) return '更新请求超时，请稍后重试'
  return '更新失败，请检查网络、发布签名与目标版本'
}

function createUpdaterController({ updater, app, clock = { setImmediate }, loadRelease, verifyArtifact, emit = () => {}, notify = () => {} }) {
  let checking = false
  let epoch = 0
  let downloadedVerified = false
  let installScheduled = false
  let installing = false
  let state = {
    status: app.isPackaged ? 'idle' : 'disabled', decision: 'none', required: false,
    currentVersion: app.getVersion(), availableVersion: null, percent: 0,
    message: app.isPackaged ? '可以检查更新' : '开发模式不检查更新',
    releaseNotes: [], downloadUrl: '', businessBusyReason: null,
  }
  updater.autoDownload = false
  updater.autoInstallOnAppQuit = false
  updater.allowDowngrade = false
  updater.allowPrerelease = false
  updater.disableWebInstaller = true

  function getState() { return { ...state, releaseNotes: [...state.releaseNotes] } }
  function broadcast(patch) { state = { ...state, ...patch }; emit(getState()) }
  function failed(error) {
    epoch++
    downloadedVerified = false
    installScheduled = false
    broadcast({ status: 'error', message: updateError(error), percent: 0, downloadUrl: '' })
  }
  async function checkForUpdates() {
    if (!app.isPackaged) return getState()
    if (checking || ['downloading', 'downloaded'].includes(state.status)) return getState()
    checking = true
    const owned = ++epoch
    downloadedVerified = false
    broadcast({ status: 'checking', message: '正在检查更新', percent: 0 })
    try {
      const release = await loadRelease()
      if (owned !== epoch) return getState()
      let decision = decideDesktopUpdate(state.currentVersion, release.desktop)
      if (decision === 'optional' && release.desktop.required) decision = 'required'
      broadcast({ decision, required: decision === 'required',
        availableVersion: decision === 'none' ? null : release.desktop.latestVersion,
        releaseNotes: release.desktop.releaseNotes,
        downloadUrl: release.desktop.downloadUrl })
      if (decision === 'none') {
        broadcast({ status: 'not-available', message: '当前已是最新版' })
        return getState()
      }
      const result = await updater.checkForUpdates()
      if (owned !== epoch) return getState()
      assertUpdaterInfo(result?.updateInfo, release)
      broadcast({ status: 'downloading', message: `发现 ${release.desktop.latestVersion}，正在下载`, percent: 0 })
      const downloaded = await updater.downloadUpdate()
      if (owned !== epoch) return getState()
      if (!Array.isArray(downloaded) || downloaded.length !== 1 || typeof downloaded[0] !== 'string') throw new Error('更新下载清单不匹配')
      await verifyArtifact(downloaded[0], release)
      if (owned !== epoch) return getState()
      downloadedVerified = true
      broadcast({ status: 'downloaded', message: '新版已验证，空闲时可重启覆盖安装', percent: 100 })
      try { notify(release.desktop.latestVersion) } catch { /* A system notification cannot invalidate a verified release. */ }
    } catch (error) {
      if (owned === epoch) failed(error)
    } finally { checking = false }
    return getState()
  }
  function installUpdate() {
    const decision = installationDecision(state.status, state.businessBusyReason)
    if (!decision.ok) return decision
    if (!downloadedVerified) return { ok: false, reason: '更新文件尚未通过安全校验' }
    if (installScheduled || installing) return { ok: false, reason: '更新安装正在准备' }
    const owned = epoch
    installScheduled = true
    clock.setImmediate(() => {
      if (owned !== epoch) return
      installScheduled = false
      const finalDecision = installationDecision(state.status, state.businessBusyReason)
      if (!finalDecision.ok || !downloadedVerified || installing) return
      installing = true
      try { updater.quitAndInstall(false, true) }
      catch (error) { installing = false; failed(error) }
    })
    return { ok: true }
  }
  function setBusinessBusy(reason) {
    broadcast({ businessBusyReason: normalizeBusyReason(reason) })
    return getState()
  }
  function onBeforeQuit(event) {
    if (installing) return
    if (state.businessBusyReason) {
      event.preventDefault()
      broadcast({ message: `${state.businessBusyReason}，完成后再退出或更新` })
      return
    }
    if (state.status === 'downloaded' && downloadedVerified) {
      event.preventDefault()
      installUpdate()
    }
  }
  updater.on('download-progress', progress => {
    if (state.status !== 'downloading') return
    const percent = Math.max(0, Math.min(100, Math.round(Number(progress.percent) || 0)))
    broadcast({ percent, message: `新版下载中 ${percent}%` })
  })
  updater.on('error', failed)
  return { getState, checkForUpdates, installUpdate, setBusinessBusy, onBeforeQuit }
}

module.exports = { createUpdaterController, updateError }
