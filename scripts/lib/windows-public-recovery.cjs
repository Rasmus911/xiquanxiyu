// Supplemental, read-only verifier. Frozen release source and signatures stay intact.
const https = require('node:https')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const {requestHttpsJson} = require('../../client/electron/https-json.cjs')
const {verifySignedRelease} = require('../../client/electron/desktop-release.cjs')
const {verifyReleaseSet, fileRecord} = require('./desktop-release.cjs')
const {supportsLegacyBridge} = require('./windows-publish.cjs')
const ORIGIN = 'https://api.pqxqxy.xyz'
const TARGETS = ['win10-x86', 'win10-x64', 'win11-x86', 'win11-x64']
const TRANSIENT = new Set(['ECONNRESET','ETIMEDOUT','EAI_AGAIN','ECONNREFUSED','ENETUNREACH','EHOSTUNREACH','EPIPE'])

function transferBudgetMs(size) {
  // Budget for a 64 KiB/s slow link, plus startup; hard cap keeps checks finite.
  return Math.min(3600000, Math.max(300000, 60000 + Math.ceil(size / 65536 * 1000)))
}
function failure(url, code, retryable, received = 0, expected = 0) {
  const error = new Error(`PUBLIC_FILE_FAILED: ${url.pathname} ${code} bytes=${received}/${expected}`)
  error.retryable = retryable
  return error
}
async function verifyHttpsFile(address, expected, options = {}) {
  const url = new URL(address)
  if (url.origin !== ORIGIN || url.username || url.password || url.hash || url.search ||
      !Number.isSafeInteger(expected?.size) || expected.size < 1 || !/^[a-f0-9]{64}$/.test(expected.sha256)) {
    throw new Error('PUBLIC_SOURCE_INVALID')
  }
  const {transport = https.request, deadlineMs = transferBudgetMs(expected.size),
    connectMs = 45000, idleMs = 90000, attempts = 3, retryDelayMs = 1500,
    progressMs = 15000, capture = false, log = () => {}} = options
  for (const [value, max] of [[deadlineMs,3600000],[connectMs,120000],[idleMs,120000],
    [attempts,3],[retryDelayMs,10000],[progressMs,60000]]) {
    if (!Number.isSafeInteger(value) || value < 1 || value > max) throw new Error('PUBLIC_LIMIT_INVALID')
  }
  if (capture && expected.size > 512 * 1024) throw new Error('PUBLIC_CAPTURE_TOO_LARGE')
  const expires = Date.now() + deadlineMs
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const remaining = expires - Date.now()
    if (remaining <= 0) throw failure(url, 'TOTAL_TIMEOUT', false, 0, expected.size)
    log(`PUBLIC_FILE_BEGIN ${url.pathname} attempt=${attempt}/${attempts} expected_bytes=${expected.size} remaining_seconds=${Math.ceil(remaining / 1000)}`)
    try {
      return await new Promise((resolve, reject) => {
        let settled = false, req, response, size = 0, idleTimer
        const chunks = [], digest = crypto.createHash('sha256'), started = Date.now()
        const totalTimer = setTimeout(() => fail('TOTAL_TIMEOUT', false), remaining)
        const connectTimer = setTimeout(() => fail('CONNECT_TIMEOUT', true), Math.min(connectMs, remaining))
        const progressTimer = setInterval(() => log(`PUBLIC_PROGRESS ${url.pathname} bytes=${size}/${expected.size} percent=${(size * 100 / expected.size).toFixed(1)} elapsed_seconds=${Math.floor((Date.now() - started) / 1000)}`), progressMs)
        function clearTimers() {
          clearTimeout(totalTimer); clearTimeout(connectTimer); clearTimeout(idleTimer); clearInterval(progressTimer)
        }
        function fail(code, retryable) {
          if (settled) return
          settled = true; clearTimers(); response?.destroy(); req?.destroy()
          reject(failure(url, code, retryable, size, expected.size))
        }
        function markActivity() {
          clearTimeout(idleTimer)
          idleTimer = setTimeout(() => fail('IDLE_TIMEOUT', true), Math.min(idleMs, Math.max(1, expires - Date.now())))
        }
        try {
          req = transport(url, {method:'GET', rejectUnauthorized:true,
            headers:{'Cache-Control':'no-cache', 'Accept-Encoding':'identity'}}, incoming => {
            response = incoming
            if (settled) { incoming.destroy(); return }
            clearTimeout(connectTimer)
            if (incoming.statusCode !== 200) {
              fail('HTTP_' + (Number(incoming.statusCode) || 0), [429,502,503,504].includes(incoming.statusCode))
              return
            }
            markActivity()
            incoming.on('data', bytes => {
              if (settled) return
              const buffer = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes)
              size += buffer.length
              if (size > expected.size) { fail('SIZE_EXCEEDED', false); return }
              digest.update(buffer)
              if (capture) chunks.push(buffer)
              if (buffer.length) markActivity()
            })
            incoming.once('aborted', () => fail('TRANSFER_ABORTED', true))
            incoming.once('error', () => fail('TRANSFER_ERROR', true))
            incoming.once('close', () => { if (!settled) fail('TRANSFER_INCOMPLETE', true) })
            incoming.once('end', () => {
              if (settled) return
              if (size !== expected.size || digest.digest('hex') !== expected.sha256) {
                fail('CONTENT_MISMATCH', false); return
              }
              settled = true; clearTimers()
              log(`PUBLIC_FILE_VERIFIED ${url.pathname} bytes=${size} sha256=${expected.sha256}`)
              resolve(capture ? Buffer.concat(chunks) : true)
            })
          })
          req.once('error', error => fail(error.code || 'TLS_OR_NETWORK_ERROR', TRANSIENT.has(error.code)))
          if (settled) req.destroy()
          else req.end()
        } catch { fail('NETWORK_ERROR', false) }
      })
    } catch (error) {
      if (!error.retryable || attempt === attempts || Date.now() + retryDelayMs >= expires) throw error
      log(`PUBLIC_RETRY ${url.pathname} next_attempt=${attempt + 1} reason=${error.message}`)
      await new Promise(resolve => setTimeout(resolve, retryDelayMs))
    }
  }
}

async function checkPublic(root, targets = TARGETS, options = {}) {
  const {scope = 'bridge', transport = https.request, requestJson = requestHttpsJson,
    log = console.log, transferOptions = {}} = options
  if (!['bridge','all'].includes(scope) || !supportsLegacyBridge(targets)) throw new Error('PUBLIC_RECHECK_SCOPE_INVALID')
  const index = await verifyReleaseSet(root, targets, {mode:'release'})
  const file = (address, record, capture = false) => verifyHttpsFile(address, record,
    {...transferOptions, transport, capture, log})
  for (const report of index.targets) {
    const id = report.profile.targetId
    const bytes = await file(`${ORIGIN}/releases/desktop/${id}.json`,
      await fileRecord(path.join(root, id), 'release.json'), true)
    const envelope = JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/, ''))
    verifySignedRelease(envelope, {trust:index.releaseTrust, profile:report.profile, currentVersion:index.version})
    log(`Public signed policy verified: ${id}`)
    if (scope === 'all') {
      for (const key of ['artifact','blockmap','updaterManifest']) {
        await file(`${ORIGIN}/updates/desktop/${id}/${report[key].fileName}`, report[key])
      }
      log(`Public signature and bytes verified: ${id}`)
    }
  }
  log('PUBLIC_PHASE=legacy-bridge-full-content')
  const bootstrap = index.targets.find(report => report.profile.targetId === 'win10-x64')
  for (const key of ['artifact','blockmap','updaterManifest']) {
    await file(`${ORIGIN}/updates/${bootstrap[key].fileName}`, bootstrap[key])
  }
  log('PUBLIC_PHASE=legacy-policy')
  const policy = await requestJson(`${ORIGIN}/releases/client-policy.json`, {allowedOrigin:ORIGIN, timeoutMs:60000})
  if (policy.schemaVersion !== 1 || policy.desktop?.latestVersion !== index.version ||
      policy.desktop?.sha256 !== bootstrap.artifact.sha256 ||
      policy.desktop?.downloadUrl !== `${ORIGIN}/updates/${bootstrap.artifact.fileName}`) {
    throw new Error('LEGACY_POLICY_MISMATCH')
  }
  return {verified:true, scope, version:index.version, buildId:index.buildId,
    channelPoliciesVerified:index.targets.length, channelFilesRedownloaded:scope === 'all',
    legacyFilesVerified:3, legacyPolicyVerified:true, cloudChanged:false,
    note:scope === 'bridge' ? 'Four channel binary-byte checks are from the earlier run; this run rechecks signed policies and full legacy content.' : 'All requested channel and legacy content checked in this run.'}
}
if (require.main === module) {
  const [root, scope = 'bridge'] = process.argv.slice(2)
  checkPublic(fs.realpathSync(root), TARGETS, {scope})
    .then(result => console.log('PUBLIC_RECHECK_OK=' + JSON.stringify(result)))
    .catch(error => { console.error(error.message); process.exitCode = 1 })
}
module.exports = {verifyHttpsFile, checkPublic, transferBudgetMs}
