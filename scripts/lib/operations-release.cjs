const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const { validVersion, verifySignedRelease } = require('../../client/electron/desktop-release.cjs')
const { compareSemver } = require('../../client/electron/update-policy.cjs')
const { getTarget } = require('../../client/electron/target-profiles.cjs')
const { inspectPayload } = require('./desktop-release.cjs')

const publicKeyPem = '-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAg5Euc1O6oXK6xaPLK8bFabECK024fg76iz7g0kjTEo0=\n-----END PUBLIC KEY-----\n'
const trust = Object.freeze({ keyId: 'b26477a9ed540ad0', publicKeyPem, testOnly: false })

function checkedFile(root, record, seen) {
  if (!record || typeof record.file !== 'string' || !record.file || /\\|:|^\//.test(record.file) ||
      record.file.split('/').some(part => !part || part === '.' || part === '..') || seen.has(record.file) ||
      !Number.isSafeInteger(record.size) || record.size < 1 || !/^[0-9a-f]{64}$/.test(record.sha256)) throw new Error('发布文件路径或记录无效')
  seen.add(record.file)
  const base = fs.realpathSync(root)
  let absolute = base
  for (const part of record.file.split('/')) {
    absolute = path.join(absolute, part)
    if (fs.lstatSync(absolute).isSymbolicLink()) throw new Error('发布文件链接无效')
  }
  if (!fs.lstatSync(absolute).isFile() || fs.statSync(absolute).size !== record.size) throw new Error('发布文件大小校验失败')
  const digest = crypto.createHash('sha256'), descriptor = fs.openSync(absolute, 'r')
  try {
    const bytes = Buffer.alloc(1024 * 1024)
    let size
    while ((size = fs.readSync(descriptor, bytes, 0, bytes.length, null))) digest.update(bytes.subarray(0, size))
  } finally { fs.closeSync(descriptor) }
  if (digest.digest('hex') !== record.sha256) throw new Error('发布文件SHA256校验失败')
  return absolute
}
function validateOperationsManifest(root, manifest, { production = false } = {}) {
  if (!manifest || manifest.schema !== 1 || manifest.testOnly === true || manifest.trust_key_id !== trust.keyId ||
      !/^[0-9a-f]{40}$/.test(manifest.source_commit) || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(manifest.build_id)) throw new Error('营业升级身份或原信任根无效')
  if (!validVersion(manifest.desktop_version) || compareSemver(manifest.desktop_version, '0.4.3') < 0 ||
      !validVersion(manifest.android_version) || compareSemver(manifest.android_version, '1.2.2') < 0 ||
      !Number.isSafeInteger(manifest.android_version_code) || manifest.android_version_code < 9) throw new Error('升级版本无效或过低')
  if (!Array.isArray(manifest.targets) || manifest.targets.length !== 1 || manifest.targets[0].target !== 'win11-x64' ||
      manifest.targets[0].runtime !== '44.5.1' || manifest.targets[0].arch !== 'x64') throw new Error('本次targets必须恰为win11-x64')
  if (manifest.targets[0].file !== `win11-x64/Xiquan-Bathhouse-Setup-${manifest.desktop_version}-win11-x64.exe` ||
      manifest.android?.file !== `xiquan-mobile-ordering-${manifest.android_version}.apk` ||
      !/^xiquan-operations-SOURCE-WEB-[A-Za-z0-9._-]+\.zip$/.test(manifest.source_web?.file)) throw new Error('安装包名称与版本不一致')
  const seen = new Set()
  for (const record of [...manifest.targets, manifest.android, manifest.source_web]) checkedFile(root, record, seen)
  const pending = []
  if (manifest.signature_status !== 'verified') pending.push('desktop_signature')
  if (manifest.android.certificate_status !== 'verified' || !/^[0-9a-f]{64}$/.test(manifest.android.certificate_sha256 || '')) pending.push('android_certificate')
  for (const key of ['backend', 'desktop', 'mobile', 'release', 'pg17_restore']) {
    if (manifest.test_results?.[key] !== 'passed') pending.push(key)
  }
  for (const key of ['windows11', 'android', 'usb_printer']) {
    if (manifest.real_device_checks?.[key] !== 'passed') pending.push(key)
  }
  if (production) {
    if (pending.length) throw new Error('正式发布签名或验收门禁尚未通过：' + pending.join(', '))
    const profile = getTarget('win11-x64'), directory = path.join(root, 'win11-x64')
    const payload = inspectPayload(directory, profile, trust)
    if (payload.version !== manifest.desktop_version || payload.identity.buildId !== manifest.build_id) throw new Error('实际桌面载荷身份不一致')
    const envelope = JSON.parse(fs.readFileSync(path.join(directory, 'release.json'), 'utf8'))
    const release = verifySignedRelease(envelope, { trust, profile, currentVersion: manifest.desktop_version })
    if (release.artifact.sha256 !== manifest.targets[0].sha256 || release.artifact.size !== manifest.targets[0].size ||
        release.buildId !== manifest.build_id) throw new Error('实际签名与安装包清单不一致')
  }
  return { targets: ['win11-x64'], production_ready: pending.length === 0 && production, pending }
}
module.exports = { validateOperationsManifest, checkedFile, trust }
if (require.main === module) {
  try {
    const root = fs.realpathSync(process.argv[2])
    const manifest = JSON.parse(fs.readFileSync(path.join(root, 'operations-manifest.json'), 'utf8').replace(/^\uFEFF/, ''))
    console.log(JSON.stringify(validateOperationsManifest(root, manifest, { production: process.argv.includes('--production') })))
  } catch (error) { console.error(error.message); process.exitCode = 1 }
}
