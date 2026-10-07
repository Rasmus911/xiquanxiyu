const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const { spawnSync } = require('node:child_process')
const { getTarget, targetIds, normalizeReleaseTrust } = require('../electron/target-profiles.cjs')
const { makeWindowsConfig } = require('./windows-config.cjs')
const { verifyReleaseSet } = require('../../scripts/lib/desktop-release.cjs')

function testTrust() {
  const { publicKey } = crypto.generateKeyPairSync('ed25519')
  return normalizeReleaseTrust({ testOnly: true, publicKeyPem: publicKey.export({ type: 'spki', format: 'pem' }),
    keyId: crypto.createHash('sha256').update(publicKey.export({ type: 'spki', format: 'der' })).digest('hex').slice(0, 16) })
}
function publicTrust(file) {
  const publicKeyPem = fs.readFileSync(file, 'utf8')
  if (!/^-----BEGIN PUBLIC KEY-----/.test(publicKeyPem)) throw new Error('只接受公开发布公钥，不读取私钥')
  const key = crypto.createPublicKey(publicKeyPem)
  return normalizeReleaseTrust({ publicKeyPem, testOnly: false,
    keyId: crypto.createHash('sha256').update(key.export({ type: 'spki', format: 'der' })).digest('hex').slice(0, 16) })
}
async function buildWindowsRelease({ projectRoot, version, buildId, targets = targetIds, trust, offlineRuntimeCache, skipRenderer = false, dryRun = false }, boundary = {}) {
  if (!Array.isArray(targets) || !targets.length || new Set(targets).size !== targets.length) throw new Error('构建目标集无效')
  const configs = targets.map(targetId => makeWindowsConfig({ projectRoot, version, buildId, targetId, trust }))
  const { offlineRuntimeDownloader, prepareRuntime } = require('./runtime-download.cjs')
  const offlineDownload = offlineRuntimeCache === undefined ? undefined : offlineRuntimeDownloader(offlineRuntimeCache)
  if (require(path.join(projectRoot, 'client/package.json')).version !== version) throw new Error('根应用版本与构建版本不一致')
  const releaseRoot = path.join(projectRoot, 'release/windows', version, buildId)
  if (dryRun) return { dryRun: true, releaseRoot, configs }
  if (fs.existsSync(releaseRoot)) throw new Error('构建目录已存在，请使用新的BuildId；旧文件不会被覆盖')
  fs.mkdirSync(path.join(releaseRoot, 'configs'), { recursive: true })
  fs.writeFileSync(path.join(releaseRoot, 'release-public-key.pem'), trust.publicKeyPem, 'utf8')
  const rendererOptions = { buildId, apiBaseUrl: 'https://api.pqxqxy.xyz/api' }
  const buildRenderer = boundary.buildRenderer || (async options => {
    const result = spawnSync('npm.cmd', ['run', 'build'], { cwd: path.join(projectRoot, 'client'), stdio: 'inherit', shell: true,
      env: { ...process.env, VITE_BUILD_ID: options.buildId, VITE_API_BASE_URL: options.apiBaseUrl } })
    if (result.error || result.status !== 0) throw new Error('Chromium108页面构建失败，已停止')
  })
  if (!skipRenderer) await buildRenderer(rendererOptions)
  const buildTarget = boundary.buildTarget || (async config => {
    const { build, Platform, Arch } = require('electron-builder')
    const profile = config.extraMetadata.xiquanDesktop
    const runtimeDirectory = await prepareRuntime(profile, path.join(releaseRoot, 'runtimes'), offlineDownload ? {
      downloadArtifact: offlineDownload, checksumValidation: 'pinned-official-sha256',
    } : {})
    // A verified version/architecture-specific SDK, never node_modules/electron/dist.
    config.electronDist = runtimeDirectory
    await build({ projectDir: path.join(projectRoot, 'client'), publish: 'never',
      targets: Platform.WINDOWS.createTarget(['nsis'], profile.arch === 'ia32' ? Arch.ia32 : Arch.x64), config })
  })
  const include = path.join(__dirname, 'windows-target.nsh').replace(/\$/g, '$$$$').replace(/"/g, '$\\"')
  for (const config of configs) {
    const profile = getTarget(config.extraMetadata.xiquanDesktop.targetId)
    fs.writeFileSync(config.nsis.include, `!define XQ_TARGET_FAMILY "${profile.targetId.split('-')[0]}"\n!define XQ_TARGET_ARCH "${profile.arch}"\n!include "${include}"\n`, 'utf8')
    console.log(`Building ${profile.targetId}: Electron ${profile.electronVersion}, ${profile.arch}`)
    await buildTarget(config)
  }
  const index = await verifyReleaseSet(releaseRoot, targets, { mode: 'candidate', trust })
  fs.writeFileSync(path.join(releaseRoot, 'delivery-index.json'), JSON.stringify(index, null, 2), 'utf8')
  return { ...index, releaseRoot }
}

async function cli() {
  const options = { projectRoot: path.resolve(__dirname, '../..'), buildId: `windows-${Date.now()}-${crypto.randomBytes(4).toString('hex')}` }
  for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i]
    if (arg === '--test-only') options.trust = testTrust()
    else if (arg === '--dry-run') options.dryRun = true
    else if (arg === '--skip-renderer') options.skipRenderer = true
    else if (arg === '--targets') options.targets = process.argv[++i].split(',')
    else if (arg === '--version') options.version = process.argv[++i]
    else if (arg === '--build-id') options.buildId = process.argv[++i]
    else if (arg === '--public-key') options.trust = publicTrust(process.argv[++i])
    else if (arg === '--offline-runtime-cache') options.offlineRuntimeCache = process.argv[++i]
    else throw new Error('未知构建参数')
  }
  options.version ||= require('../package.json').version
  if (!options.trust) throw new Error('请提供--public-key，或明确使用--test-only构建兼容候选')
  const result = await buildWindowsRelease(options)
  console.log(JSON.stringify(result, null, 2))
}
if (require.main === module) cli().catch(error => { console.error(error.message); process.exitCode = 1 })
module.exports = { buildWindowsRelease, testTrust, publicTrust }
