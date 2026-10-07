const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const { createRequire } = require('node:module')
const fromClient = createRequire(path.resolve(__dirname, '../../client/package.json'))
const asar = fromClient('@electron/asar')
const yaml = fromClient('js-yaml')
const { getTarget, targetIds, assertPackagedTarget, normalizeReleaseTrust } = require('../../client/electron/target-profiles.cjs')
const { assertUpdaterInfo, validVersion, verifySignedRelease } = require('../../client/electron/desktop-release.cjs')

function peArch(bytes) {
  if (bytes.length < 64 || bytes.toString('ascii', 0, 2) !== 'MZ') throw new Error('应用PE头无效')
  const offset = bytes.readUInt32LE(0x3c)
  if (offset < 64 || offset + 6 > bytes.length || bytes.toString('ascii', offset, offset + 4) !== 'PE\0\0') throw new Error('应用PE头无效')
  const machine = bytes.readUInt16LE(offset + 4)
  if (machine === 0x14c) return 'ia32'
  if (machine === 0x8664) return 'x64'
  throw new Error('应用PE架构不受支持')
}
function safeFile(root, relative) {
  const absolute = path.resolve(root, relative), prefix = fs.realpathSync(root) + path.sep
  if (!fs.realpathSync(absolute).startsWith(prefix) || !fs.lstatSync(absolute).isFile()) throw new Error('发布文件路径或类型无效')
  return absolute
}
async function fileRecord(root, fileName) {
  const absolute = safeFile(root, fileName), sha256 = crypto.createHash('sha256'), sha512 = crypto.createHash('sha512')
  let size = 0
  for await (const bytes of fs.createReadStream(absolute)) { size += bytes.length; sha256.update(bytes); sha512.update(bytes) }
  return { fileName, size, sha256: sha256.digest('hex'), sha512: sha512.digest('base64') }
}
function inspectPayload(directory, profile, trust) {
  const unpackedName = profile.arch === 'ia32' ? 'win-ia32-unpacked' : 'win-unpacked'
  const exe = safeFile(directory, path.join(unpackedName, '溪泉洗浴管理系统.exe'))
  const descriptor = fs.openSync(exe, 'r')
  let bytes
  try {
    const head = Buffer.alloc(64); fs.readSync(descriptor, head, 0, 64, 0)
    const offset = head.readUInt32LE(0x3c)
    if (offset > 1024 * 1024) throw new Error('应用PE头超出范围')
    bytes = Buffer.alloc(offset + 6); fs.readSync(descriptor, bytes, 0, bytes.length, 0)
  } finally { fs.closeSync(descriptor) }
  const payloadArch = peArch(bytes)
  if (payloadArch !== profile.arch) throw new Error('应用真实架构与目标不匹配')
  const archive = safeFile(directory, path.join(unpackedName, 'resources/app.asar'))
  const metadata = JSON.parse(asar.extractFile(archive, 'package.json').toString('utf8'))
  const identity = assertPackagedTarget(metadata.xiquanDesktop, { platform: 'win32', arch: profile.arch,
    release: profile.allowedHosts[0] === 'win7' ? '6.1.7601' : profile.allowedHosts[0] === 'win11' ? '10.0.22000' : '10.0.10240',
    electronVersion: profile.electronVersion })
  if (identity.targetId !== profile.targetId || !validVersion(metadata.version) || metadata.main !== 'electron/main.cjs') throw new Error('应用载荷标识不匹配')
  if (trust && (identity.releaseTrust.keyId !== trust.keyId || identity.releaseTrust.publicKeyPem !== trust.publicKeyPem || identity.releaseTrust.testOnly !== trust.testOnly)) throw new Error('应用发布公钥不匹配')
  const entries = asar.listPackage(archive).map(value => value.replace(/\\/g, '/').replace(/^\//, ''))
  for (const required of ['dist/index.html', 'electron/main.cjs', 'electron/preload.cjs', 'electron/updater.cjs', 'electron/target-profiles.cjs']) {
    if (!entries.includes(required)) throw new Error('应用载荷缺少页面或桌面桥接')
  }
  // The only release public key belongs in validated package metadata, not loose key files.
  // Reject by filename before any possible private-key contents can be read.
  if (entries.some(value => /(^|\/)(\.env(?:\..*)?|private)(\/|$)|\.(pem|key|jks|sqlite|db|pfx|p12)$/i.test(value))) throw new Error('应用载荷存在禁止发布的数据文件')
  return { identity, version: metadata.version, payloadArch, payloadExe: exe }
}
async function inspectArtifacts(directory, { targetId, trust } = {}) {
  const profile = getTarget(targetId)
  const normalized = trust ? normalizeReleaseTrust(trust) : undefined
  const payload = inspectPayload(directory, profile, normalized)
  const fileName = `Xiquan-Bathhouse-Setup-${payload.version}-${targetId}.exe`
  const artifact = await fileRecord(directory, fileName)
  const blockmap = await fileRecord(directory, fileName + '.blockmap')
  const updaterManifest = await fileRecord(directory, 'latest.yml')
  const manifest = yaml.load(fs.readFileSync(safeFile(directory, 'latest.yml'), 'utf8'))
  assertUpdaterInfo(manifest, { desktop: { latestVersion: payload.version }, artifact })
  if (!artifact.size || !blockmap.size || !updaterManifest.size) throw new Error('发布文件为空')
  return { profile, version: payload.version, buildId: payload.identity.buildId, releaseTrust: payload.identity.releaseTrust,
    payloadArch: payload.payloadArch, payloadExe: payload.payloadExe, artifact, blockmap, updaterManifest }
}
function makeReleasePayload(report, { sequence, minimumVersion, required = false, releaseNotes = [], publishedAt = new Date().toISOString() }) {
  if (!Number.isSafeInteger(sequence) || sequence < 1 || !validVersion(minimumVersion)) throw new Error('发布序号或最低版本无效')
  return { schemaVersion: 2, keyId: report.releaseTrust.keyId, sequence, buildId: report.buildId, ...report.profile,
    desktop: { latestVersion: report.version, minimumVersion, required,
      downloadUrl: `https://api.pqxqxy.xyz/updates/desktop/${report.profile.targetId}/${report.artifact.fileName}`,
      sha256: report.artifact.sha256, releaseNotes, publishedAt },
    artifact: report.artifact, blockmap: report.blockmap, updaterManifest: report.updaterManifest }
}
async function verifyReleaseSet(root, expectedTargets = targetIds, { mode = 'candidate', trust } = {}) {
  if (!['candidate', 'release'].includes(mode) || !Array.isArray(expectedTargets) || !expectedTargets.length || new Set(expectedTargets).size !== expectedTargets.length) throw new Error('发布检查模式或目标集无效')
  let anchor = trust ? normalizeReleaseTrust(trust) : null
  const targets = []
  let version, buildId
  for (const id of expectedTargets) {
    const report = await inspectArtifacts(path.join(root, getTarget(id).targetId), { targetId: id, trust: anchor })
    anchor ||= report.releaseTrust
    version ||= report.version; buildId ||= report.buildId
    if (report.version !== version || report.buildId !== buildId) throw new Error('请求目标版本或构建标识不一致')
    if (mode === 'release') {
      if (anchor.testOnly) throw new Error('测试包不能正式发布')
      const envelope = JSON.parse(fs.readFileSync(safeFile(path.join(root, id), 'release.json'), 'utf8'))
      const verified = verifySignedRelease(envelope, { trust: anchor, profile: report.profile, currentVersion: report.version })
      for (const field of ['artifact', 'blockmap', 'updaterManifest']) {
        for (const key of ['fileName', 'sha256', 'size', 'sha512']) {
          if (verified[field][key] !== undefined && verified[field][key] !== report[field][key]) throw new Error('签名清单与实际文件不匹配')
        }
      }
      if (verified.buildId !== report.buildId || verified.electronVersion !== report.profile.electronVersion) throw new Error('签名构建标识不匹配')
    }
    const { payloadExe, ...publicReport } = report
    targets.push(publicReport)
  }
  return { schemaVersion: 1, version, buildId, complete: targets.length === expectedTargets.length,
    requestedTargets: [...expectedTargets], allTargets: targetIds.every(id => expectedTargets.includes(id)),
    signed: mode === 'release', testOnly: anchor.testOnly, releaseTrust: anchor,
    acceptance: { realOs: 'not-tested', usbPrinter: 'not-tested', inPlaceUpdate: 'not-tested', runtimeSmoke: 'not-tested' }, targets }
}
module.exports = { peArch, safeFile, fileRecord, inspectPayload, inspectArtifacts, makeReleasePayload, verifyReleaseSet }
