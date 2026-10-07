const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const { EventEmitter } = require('node:events')
const { Readable } = require('node:stream')
const { getTarget, targetIds, assertPackagedTarget } = require('../electron/target-profiles.cjs')
const { deriveTargetUrls } = require('../electron/update-url.cjs')
const { requestHttpsJson } = require('../electron/https-json.cjs')
const { verifySignedRelease, sha256 } = require('../electron/desktop-release.cjs')
const { installationDecision } = require('../electron/updater-guard.cjs')
const { windowBounds } = require('../electron/compatibility.cjs')
const { menuTemplate, isTrustedIpc } = require('../electron/security.cjs')
const { createUpdaterController } = require('../electron/updater-controller.cjs')

async function smoke() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519')
  const trust = { publicKeyPem: publicKey.export({ type: 'spki', format: 'pem' }), testOnly: false,
    keyId: sha256(publicKey.export({ type: 'spki', format: 'der' })).slice(0, 16) }
  for (const targetId of targetIds) {
    const profile = getTarget(targetId)
    const identity = assertPackagedTarget({ schemaVersion: 1, ...profile, buildId: 'smoke', releaseTrust: trust }, {
      platform: 'win32', arch: profile.arch, release: targetId.startsWith('win7') ? '6.1.7601' : targetId.startsWith('win11') ? '10.0.22000' : '10.0.10240', electronVersion: profile.electronVersion })
    assert.equal(identity.targetId, targetId)
    assert.equal(deriveTargetUrls('https://api.pqxqxy.xyz/api', targetId).feedUrl.endsWith(`/${targetId}/`), true)
  }
  const profile = getTarget('win7-x86'), bytes = Buffer.from('fixture')
  const artifact = { fileName: 'Xiquan-Bathhouse-Setup-0.4.3-win7-x86.exe', size: bytes.length,
    sha256: sha256(bytes), sha512: crypto.createHash('sha512').update(bytes).digest('base64') }
  const payload = { schemaVersion: 2, ...profile, keyId: trust.keyId, buildId: 'smoke', sequence: 1,
    desktop: { latestVersion: '0.4.3', minimumVersion: '0.4.2', required: false, releaseNotes: [], publishedAt: new Date().toISOString(),
      downloadUrl: `https://api.pqxqxy.xyz/updates/desktop/win7-x86/${artifact.fileName}`, sha256: artifact.sha256 }, artifact,
    blockmap: { fileName: artifact.fileName + '.blockmap', size: 1, sha256: 'a'.repeat(64) }, updaterManifest: { fileName: 'latest.yml', sha256: 'b'.repeat(64) } }
  const body = Buffer.from(JSON.stringify(payload)), envelope = { payload: body.toString('base64'), signature: crypto.sign(null, body, privateKey).toString('base64') }
  const release = verifySignedRelease(envelope, { trust, profile, currentVersion: '0.4.2' })
  assert.equal(release.sequence, 1)
  assert.throws(() => verifySignedRelease({ ...envelope, signature: Buffer.alloc(64).toString('base64') }, { trust, profile, currentVersion: '0.4.2' }))
  const transport = (_url, options, callback) => {
    assert.equal(options.rejectUnauthorized, true)
    const request = new EventEmitter(); request.destroy = () => {}
    request.end = () => process.nextTick(() => { const response = Readable.from([Buffer.from('{"ok":true}')]); response.statusCode = 200; callback(response) })
    return request
  }
  assert.equal((await requestHttpsJson('https://api.pqxqxy.xyz/fixture', { request: transport, allowedOrigin: 'https://api.pqxqxy.xyz' })).ok, true)
  assert.equal(installationDecision('downloaded', 'busy').ok, false)
  assert.equal(windowBounds({ width: 819, height: 580 }).width, 819)
  assert.equal(isTrustedIpc({ sender: { id: 99 } }, 1, 'file:///index.html'), false)
  assert.ok(JSON.stringify(menuTemplate(false)).includes('CommandOrControl+C'))
  const updater = new EventEmitter(); updater.checkForUpdates = async () => ({ updateInfo: { version: '0.4.3', files: [{ url: artifact.fileName, size: artifact.size, sha512: artifact.sha512 }] } })
  updater.downloadUpdate = async () => ['fixture.exe']; updater.quitAndInstall = () => { throw new Error('smoke must never install') }
  const controller = createUpdaterController({ updater, app: { isPackaged: true, getVersion: () => '0.4.2' }, loadRelease: async () => release, verifyArtifact: async () => {} })
  await controller.checkForUpdates(); assert.equal(controller.getState().status, 'downloaded')
  controller.setBusinessBusy('fixture'); assert.equal(controller.installUpdate().ok, false)
  console.log(JSON.stringify({ passed: true, arch: process.arch, electron: process.versions.electron || null,
    node: process.versions.node, chromium: process.versions.chrome || null, globalFetchPresent: typeof fetch === 'function', network: false, installed: false }))
}
smoke().catch(error => { console.error(error.message); process.exitCode = 1 })
