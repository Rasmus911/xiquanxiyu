const crypto = require('node:crypto')
const fs = require('node:fs')
const { getTarget, normalizeReleaseTrust } = require('./target-profiles.cjs')
const { normalizeDesktopPolicy, compareSemver } = require('./update-policy.cjs')
const { deriveTargetUrls } = require('./update-url.cjs')

function fail(message = '更新策略与当前安装目标不匹配') { throw new TypeError(message) }
function sha256(bytes) { return crypto.createHash('sha256').update(bytes).digest('hex') }
function validVersion(value) {
  return typeof value === 'string' && /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(value) &&
    value.split('.').every(part => Number.isSafeInteger(Number(part)))
}
function validHash(value) { return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value) }
function validSha512(value) {
  return typeof value === 'string' && value.length === 88 && Buffer.from(value, 'base64').length === 64 &&
    Buffer.from(value, 'base64').toString('base64') === value
}
function assertRuntime(profile, version) {
  if (!validVersion(version)) fail()
  const major = Number(version.split('.')[0])
  if ((profile.runtimeFamily === 'win7-legacy' && major !== 22) ||
      (profile.runtimeFamily === 'windows-ia32' && major !== 43) ||
      (profile.runtimeFamily === 'windows-x64' && major < 44)) fail()
}

function verifySignedRelease(envelope, context) {
  const trust = normalizeReleaseTrust(context.trust)
  if (trust.testOnly) fail('测试包不接受正式自动更新')
  if (!envelope || typeof envelope.payload !== 'string' || envelope.payload.length > 350000 ||
      typeof envelope.signature !== 'string' || envelope.signature.length !== 88) fail('更新发布签名无效')
  const bytes = Buffer.from(envelope.payload, 'base64')
  const signature = Buffer.from(envelope.signature, 'base64')
  let valid = false
  try {
    valid = bytes.length > 0 && bytes.length <= 256 * 1024 && bytes.toString('base64') === envelope.payload &&
      signature.length === 64 && signature.toString('base64') === envelope.signature &&
      crypto.verify(null, bytes, trust.publicKeyPem, signature)
  } catch { valid = false }
  if (!valid) fail('更新发布签名无效，已停止更新')
  let value
  try { value = JSON.parse(bytes.toString('utf8')) } catch { fail('更新发布格式无效') }
  const profile = getTarget(context.profile.targetId)
  if (!value || value.schemaVersion !== 2 || value.keyId !== trust.keyId || value.targetId !== profile.targetId ||
      value.arch !== profile.arch || value.runtimeFamily !== profile.runtimeFamily ||
      JSON.stringify(value.allowedHosts) !== JSON.stringify(profile.allowedHosts) ||
      typeof value.buildId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(value.buildId)) fail()
  assertRuntime(profile, value.electronVersion)
  const payloadHash = sha256(bytes)
  const lastSequence = context.lastSequence ?? 0
  if (!Number.isSafeInteger(value.sequence) || value.sequence < 1 || !Number.isSafeInteger(lastSequence) || lastSequence < 0 ||
      value.sequence < lastSequence || (value.sequence === lastSequence && payloadHash !== context.lastPayloadHash)) fail('更新发布序号回退或冲突')
  const raw = value.desktop
  if (!raw || !validVersion(raw.latestVersion) || !validVersion(raw.minimumVersion) || !validVersion(context.currentVersion) ||
      typeof raw.required !== 'boolean' || !Array.isArray(raw.releaseNotes) || raw.releaseNotes.length > 30 ||
      raw.releaseNotes.some(note => typeof note !== 'string' || note.length > 600)) fail('桌面版本策略无效')
  const desktop = normalizeDesktopPolicy(raw)
  const published = Date.parse(raw.publishedAt)
  const now = Number(context.now ?? new Date())
  if (!desktop || !Number.isFinite(published) || !Number.isFinite(now) || published > now + 10 * 60 * 1000 ||
      compareSemver(desktop.latestVersion, context.currentVersion) < 0) fail('桌面版本策略无效或版本回退')
  const fileName = `Xiquan-Bathhouse-Setup-${desktop.latestVersion}-${profile.targetId}.exe`
  const artifact = value.artifact
  const blockmap = value.blockmap
  const manifest = value.updaterManifest
  const urls = deriveTargetUrls('https://api.pqxqxy.xyz/api', profile.targetId)
  if (!artifact || artifact.fileName !== fileName || !Number.isSafeInteger(artifact.size) || artifact.size < 1 ||
      !validHash(artifact.sha256) || !validSha512(artifact.sha512) || artifact.sha256 !== desktop.sha256 ||
      raw.downloadUrl !== `${urls.feedUrl}${fileName}`) fail('更新文件与签名目标不匹配')
  if (!blockmap || blockmap.fileName !== `${fileName}.blockmap` || !Number.isSafeInteger(blockmap.size) ||
      blockmap.size < 1 || !validHash(blockmap.sha256) || !manifest ||
      manifest.fileName !== 'latest.yml' || !validHash(manifest.sha256)) fail('更新文件清单无效')
  return Object.freeze({
    sequence: value.sequence, buildId: value.buildId, electronVersion: value.electronVersion, payloadHash,
    profile, desktop: Object.freeze(desktop),
    artifact: Object.freeze({ fileName, size: artifact.size, sha256: artifact.sha256, sha512: artifact.sha512 }),
    blockmap: Object.freeze({ fileName: blockmap.fileName, size: blockmap.size, sha256: blockmap.sha256 }),
    updaterManifest: Object.freeze({ fileName: 'latest.yml', sha256: manifest.sha256 }),
  })
}

function assertUpdaterInfo(info, release) {
  const artifact = release?.artifact
  if (!artifact || !info || info.version !== release.desktop.latestVersion || !Array.isArray(info.files) ||
      info.files.length !== 1 || info.packages) fail('更新下载清单与签名发布不匹配')
  const file = info.files[0]
  if (!file || file.url !== artifact.fileName || file.sha512 !== artifact.sha512 || file.size !== artifact.size ||
      (info.path !== undefined && info.path !== artifact.fileName) ||
      (info.sha512 !== undefined && info.sha512 !== artifact.sha512)) fail('更新下载清单与签名发布不匹配')
}

async function verifyDownloadedArtifact(filePath, release) {
  if (typeof filePath !== 'string') fail('更新文件校验失败')
  const stat = await fs.promises.lstat(filePath)
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size !== release.artifact.size) fail('更新文件校验失败')
  const hash256 = crypto.createHash('sha256')
  const hash512 = crypto.createHash('sha512')
  let size = 0
  for await (const chunk of fs.createReadStream(filePath)) {
    size += chunk.length
    hash256.update(chunk)
    hash512.update(chunk)
  }
  if (size !== release.artifact.size || hash256.digest('hex') !== release.artifact.sha256 ||
      hash512.digest('base64') !== release.artifact.sha512) fail('更新文件校验失败')
}

module.exports = { verifySignedRelease, assertUpdaterInfo, verifyDownloadedArtifact, validVersion, sha256 }
