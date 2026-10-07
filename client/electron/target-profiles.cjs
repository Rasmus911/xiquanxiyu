const crypto = require('node:crypto')

const profiles = [
  ['win7-x86', 'ia32', '22.3.27', 'win7-legacy', ['win7']],
  ['win7-x64', 'x64', '22.3.27', 'win7-legacy', ['win7']],
  ['win10-x86', 'ia32', '43.7.7', 'windows-ia32', ['win10', 'win11']],
  ['win10-x64', 'x64', '44.5.1', 'windows-x64', ['win10', 'win11']],
  ['win11-x86', 'ia32', '43.7.7', 'windows-ia32', ['win11']],
  ['win11-x64', 'x64', '44.5.1', 'windows-x64', ['win11']],
].map(([targetId, arch, electronVersion, runtimeFamily, allowedHosts]) => Object.freeze({
  targetId, arch, electronVersion, runtimeFamily, allowedHosts: Object.freeze(allowedHosts),
}))
const targetIds = Object.freeze(profiles.map(profile => profile.targetId))

function getTarget(targetId) {
  const profile = profiles.find(value => value.targetId === targetId)
  if (!profile) throw new TypeError('未知的桌面安装目标')
  return profile
}

function detectWindowsFamily(release) {
  const match = /^(\d+)\.(\d+)\.(\d+)(?:\.\d+)?$/.exec(String(release || ''))
  if (!match) return null
  const [major, minor, build] = match.slice(1).map(Number)
  if (major === 6 && minor === 1 && build === 7601) return 'win7'
  if (major === 10 && minor === 0 && build >= 22000) return 'win11'
  if (major === 10 && minor === 0 && build >= 10240) return 'win10'
  return null
}

function assertHost(profile, host) {
  if (!host || host.platform !== 'win32' || host.arch !== profile.arch ||
      !profile.allowedHosts.includes(detectWindowsFamily(host.release))) {
    throw new TypeError('此安装包与当前系统或程序架构不匹配，请选择对应版本')
  }
}

function normalizeReleaseTrust(value) {
  if (!value || typeof value.publicKeyPem !== 'string' || value.publicKeyPem.length > 16384 ||
      !/^-----BEGIN PUBLIC KEY-----[\s\S]+-----END PUBLIC KEY-----\s*$/.test(value.publicKeyPem) ||
      typeof value.testOnly !== 'boolean') throw new TypeError('桌面发布公钥或测试标记无效')
  let publicKey
  try { publicKey = crypto.createPublicKey(value.publicKeyPem) } catch { throw new TypeError('桌面发布公钥无效') }
  if (publicKey.asymmetricKeyType !== 'ed25519') throw new TypeError('桌面发布公钥算法无效')
  const keyId = crypto.createHash('sha256').update(publicKey.export({ type: 'spki', format: 'der' })).digest('hex').slice(0, 16)
  if (value.keyId !== keyId) throw new TypeError('桌面发布公钥指纹不匹配')
  return Object.freeze({ keyId, publicKeyPem: publicKey.export({ type: 'spki', format: 'pem' }), testOnly: value.testOnly })
}

function assertPackagedTarget(metadata, runtime) {
  if (!metadata || metadata.schemaVersion !== 1 ||
      typeof metadata.buildId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(metadata.buildId)) {
    throw new TypeError('桌面安装包缺少有效的构建身份')
  }
  const profile = getTarget(metadata.targetId)
  if (metadata.arch !== profile.arch || metadata.electronVersion !== profile.electronVersion ||
      metadata.runtimeFamily !== profile.runtimeFamily ||
      JSON.stringify(metadata.allowedHosts) !== JSON.stringify(profile.allowedHosts) ||
      runtime?.electronVersion !== metadata.electronVersion) throw new TypeError('桌面安装包运行环境标识不匹配')
  assertHost(profile, runtime)
  const releaseTrust = normalizeReleaseTrust(metadata.releaseTrust)
  return Object.freeze({ ...profile, buildId: metadata.buildId, releaseTrust })
}

module.exports = { getTarget, targetIds, detectWindowsFamily, assertHost, assertPackagedTarget, normalizeReleaseTrust }
