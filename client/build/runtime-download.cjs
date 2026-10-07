const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const { peArch, fileRecord } = require('../../scripts/lib/desktop-release.cjs')
const { getTarget } = require('../electron/target-profiles.cjs')

const runtimePins = Object.freeze({
  '22.3.27-ia32': Object.freeze({ fileName: 'electron-v22.3.27-win32-ia32.zip', size: 91173960,
    sha256: '1119ac7112590cb9c10a8c9b0bb5be65c0e11648a4f1311e6b7a5a00e497c2ce' }),
  '22.3.27-x64': Object.freeze({ fileName: 'electron-v22.3.27-win32-x64.zip', size: 97021975,
    sha256: 'ad723ed7dad32f9459f7a9de1fd6d718cf713c4809c2431503bea62ce8f786e6' }),
  '43.7.7-ia32': Object.freeze({ fileName: 'electron-v43.7.7-win32-ia32.zip', size: 131079750,
    sha256: 'a170eeedf4a216b3b0672b151294e7aef0b4fdc15ae5c207ea3f9f37c4a14c42' }),
  '44.5.1-x64': Object.freeze({ fileName: 'electron-v44.5.1-win32-x64.zip', size: 157998329,
    sha256: '9b382492dcfee91f8f9e92c91f7972550a1b95d2299cac72279dab33a600d7db' }),
})
function offlineRuntimeDownloader(cacheDirectory, pins = runtimePins) {
  if (typeof cacheDirectory !== 'string' || !path.isAbsolute(cacheDirectory)) throw new Error('离线缓存必须为绝对目录')
  return async options => {
    const pin = pins[`${options.version}-${options.arch}`]
    if (!pin || options.platform !== 'win32' || options.artifactName !== 'electron' ||
        pin.fileName !== `electron-v${options.version}-win32-${options.arch}.zip`) throw new Error('运行环境没有可信固定pin')
    const zip = path.join(cacheDirectory, pin.fileName)
    if (!fs.existsSync(zip)) throw new Error('离线缓存档案缺失；不会自动联网或删除原缓存')
    const record = await fileRecord(cacheDirectory, pin.fileName)
    if (record.size !== pin.size || record.sha256 !== pin.sha256) throw new Error('离线缓存大小或SHA256校验失败')
    return zip
  }
}

async function prepareRuntime(profile, runtimeRoot, boundary = {}) {
  const expected = getTarget(profile.targetId)
  if (profile.arch !== expected.arch || profile.electronVersion !== expected.electronVersion || !path.isAbsolute(runtimeRoot)) throw new Error('运行环境目标无效')
  const directory = path.join(runtimeRoot, `${profile.electronVersion}-${profile.arch}`)
  const evidence = path.join(directory, 'sdk-evidence.json')
  if (!fs.existsSync(evidence)) {
    if (fs.existsSync(directory)) throw new Error('运行环境解压不完整，请使用新的构建目录')
    const downloadArtifact = boundary.downloadArtifact || require('@electron/get').downloadArtifact
    const extractZip = boundary.extractZip || (async (archive, { dir }) => {
      const result = spawnSync('powershell.exe', ['-NoProfile', '-Command',
        "Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::ExtractToDirectory($env:XIQUAN_SDK_ARCHIVE,$env:XIQUAN_SDK_OUTPUT)"],
      { env: { ...process.env, XIQUAN_SDK_ARCHIVE: archive, XIQUAN_SDK_OUTPUT: dir }, encoding: 'utf8', windowsHide: true, timeout: 120000 })
      if (result.error || result.status !== 0) throw new Error('Windows运行环境ZIP解压失败')
    })
    // Normal mode uses freshly downloaded official SHASUMS; explicit offline mode verifies a pinned archive.
    const zip = await downloadArtifact({ artifactName: 'electron', version: profile.electronVersion, platform: 'win32', arch: profile.arch })
    fs.mkdirSync(directory, { recursive: true })
    await extractZip(zip, { dir: directory })
    const record = await fileRecord(path.dirname(zip), path.basename(zip))
    fs.writeFileSync(evidence, JSON.stringify({ version: profile.electronVersion, arch: profile.arch,
      fileName: record.fileName, sha256: record.sha256, checksumValidation: boundary.checksumValidation || 'official-shasums256', source: 'https://github.com/electron/electron/releases' }), 'utf8')
  }
  if (fs.readFileSync(path.join(directory, 'version'), 'utf8').trim().replace(/^v/, '') !== profile.electronVersion) throw new Error('运行环境版本不匹配')
  if (peArch(fs.readFileSync(path.join(directory, 'electron.exe'))) !== profile.arch) throw new Error('运行环境架构不匹配')
  return directory
}
module.exports = { prepareRuntime, offlineRuntimeDownloader }
