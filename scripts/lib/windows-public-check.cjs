const https = require('node:https')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const { requestHttpsJson } = require('../../client/electron/https-json.cjs')
const { verifySignedRelease } = require('../../client/electron/desktop-release.cjs')
const { verifyReleaseSet, fileRecord } = require('./desktop-release.cjs')

async function verifyHttpsFile(address, expected, transport = https.request) {
  const url = new URL(address)
  if (url.origin !== 'https://api.pqxqxy.xyz' || url.username || url.password || url.hash ||
      !Number.isSafeInteger(expected.size) || expected.size < 1 || !/^[0-9a-f]{64}$/.test(expected.sha256)) throw new Error('公开文件校验来源无效')
  return new Promise((resolve, reject) => {
    let done = false, request, response
    const digest = crypto.createHash('sha256'); let size = 0
    const timeout = setTimeout(() => fail(new Error('公开文件请求超时')), 300_000)
    function fail(error) {
      if (done) return
      done = true; clearTimeout(timeout); response?.destroy(); request?.destroy()
      reject(error)
    }
    try {
      request = transport(url, { method: 'GET', rejectUnauthorized: true }, result => {
        response = result
        if (result.statusCode !== 200) { result.resume(); fail(new Error('公开文件HTTP状态无效，重定向不受支持')); return }
        result.on('data', bytes => {
          size += bytes.length
          if (size > expected.size) fail(new Error('公开文件大小校验失败'))
          else digest.update(bytes)
        })
        result.on('error', () => fail(new Error('公开文件传输失败')))
        result.on('aborted', () => fail(new Error('公开文件传输中断')))
        result.on('close', () => { if (!done) fail(new Error('公开文件未完整传输')) })
        result.on('end', () => {
          if (done) return
          if (size !== expected.size || digest.digest('hex') !== expected.sha256) { fail(new Error('公开文件内容校验失败')); return }
          done = true; clearTimeout(timeout); resolve(true)
        })
      })
      request.on('error', () => fail(new Error('公开文件TLS或网络请求失败')))
      request.setTimeout(30_000, () => fail(new Error('公开文件请求超时')))
      request.end()
    } catch { fail(new Error('公开文件网络请求失败')) }
  })
}
async function checkPublic(root, targets) {
  const index = await verifyReleaseSet(root, targets, { mode: 'release' })
  const origin = 'https://api.pqxqxy.xyz'
  for (const report of index.targets) {
    const id = report.profile.targetId, policyPath = `releases/desktop/${id}.json`
    await verifyHttpsFile(`${origin}/${policyPath}`, await fileRecord(path.join(root, id), 'release.json'))
    const envelope = await requestHttpsJson(`${origin}/${policyPath}`, { allowedOrigin: origin })
    verifySignedRelease(envelope, { trust: index.releaseTrust, profile: report.profile, currentVersion: index.version })
    for (const key of ['artifact', 'blockmap', 'updaterManifest']) {
      await verifyHttpsFile(`${origin}/updates/desktop/${id}/${report[key].fileName}`, report[key])
    }
    console.log(`Public signature and bytes verified: ${id}`)
  }
  if (!index.allTargets) return
  const bootstrap = index.targets.find(report => report.profile.targetId === 'win10-x64')
  for (const key of ['artifact', 'blockmap', 'updaterManifest']) await verifyHttpsFile(`${origin}/updates/${bootstrap[key].fileName}`, bootstrap[key])
  const policy = await requestHttpsJson(`${origin}/releases/client-policy.json`, { allowedOrigin: origin })
  if (policy.schemaVersion !== 1 || policy.desktop?.latestVersion !== index.version ||
      policy.desktop?.sha256 !== bootstrap.artifact.sha256 || policy.desktop?.downloadUrl !== `${origin}/updates/${bootstrap.artifact.fileName}`) throw new Error('旧客户端过渡策略不匹配')
}
if (require.main === module) checkPublic(fs.realpathSync(process.argv[2]), process.argv[3] === undefined ? undefined : process.argv[3].split(',')).catch(error => { console.error(error.message); process.exitCode = 1 })
module.exports = { verifyHttpsFile, checkPublic }
