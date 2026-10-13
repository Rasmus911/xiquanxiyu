const test = require('node:test')
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const { EventEmitter } = require('node:events')
const { PassThrough } = require('node:stream')
const { verifyHttpsFile, checkPublic, transferBudgetMs } = require('./windows-public-recovery.cjs')
const { fixture } = require('./desktop-release-fixture.cjs')
const { inspectArtifacts, makeReleasePayload } = require('./desktop-release.cjs')

const origin = 'https://api.pqxqxy.xyz'
const targets = ['win10-x86', 'win10-x64', 'win11-x86', 'win11-x64']
const record = bytes => ({size: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex')})

// The external HTTP boundary alone is substituted; hashing, signatures,
// timers, release validation and stream lifecycle run as production code.
function transportFor(plan) {
  const requests = []
  function transport(url, options, callback) {
    requests.push(url.pathname)
    assert.equal(url.origin, origin)
    assert.equal(options.rejectUnauthorized, true)
    const req = new EventEmitter()
    let response, stopped = false
    const timers = []
    req.destroy = () => { stopped = true; timers.forEach(clearTimeout); response?.destroy() }
    req.end = () => queueMicrotask(() => {
      if (stopped) return
      const item = plan(url.pathname, requests.length)
      if (item.error) { req.emit('error', Object.assign(new Error('external request failed'), {code:item.error})); return }
      if (item.noResponse) return
      response = new PassThrough()
      response.statusCode = item.status || 200
      callback(response)
      if (stopped) return
      if (item.stall) return
      const chunks = item.chunks || [item.body]
      chunks.forEach((chunk, i) => timers.push(setTimeout(() => {
        if (!stopped) response.write(chunk)
      }, (i + 1) * (item.gap || 1))))
      timers.push(setTimeout(() => { if (!stopped) response.end() }, (chunks.length + 1) * (item.gap || 1)))
    })
    return req
  }
  return {transport, requests}
}
const fast = {deadlineMs: 500, connectMs: 100, idleMs: 100, retryDelayMs: 1, progressMs: 10}

test('120 MB installer gets a finite slow-link budget exceeding five minutes', () => {
  assert.ok(transferBudgetMs(120764385) > 20 * 60 * 1000)
  assert.ok(transferBudgetMs(120764385) <= 60 * 60 * 1000)
  assert.ok(transferBudgetMs(400) <= 5 * 60 * 1000)
})
test('continuous slow transfer is verified by bytes and hash, with progress reports', async () => {
  const bytes = Buffer.from('six-chunks')
  const network = transportFor(() => ({chunks: [bytes.subarray(0, 3), bytes.subarray(3)], gap: 20}))
  const logs = []
  assert.equal(await verifyHttpsFile(origin + '/updates/slow.exe', record(bytes),
    {...fast, idleMs: 40, transport: network.transport, log: line => logs.push(line)}), true)
  assert.ok(logs.some(line => line.includes('PUBLIC_PROGRESS') && line.includes('/updates/slow.exe')))
  assert.equal(network.requests.length, 1)
})
test('stalled public GET retries within a finite budget, without uploading or signing', async () => {
  const bytes = Buffer.from('verified retry')
  const network = transportFor((_name, attempt) => attempt === 1 ? {stall:true} : {body:bytes})
  assert.equal(await verifyHttpsFile(origin + '/updates/retry.exe', record(bytes),
    {...fast, idleMs:15, transport:network.transport}), true)
  assert.equal(network.requests.length, 2)
})
test('connection timeout identifies exact failed file and is bounded', async () => {
  const network = transportFor(() => ({noResponse:true}))
  await assert.rejects(() => verifyHttpsFile(origin + '/updates/connection.exe', record(Buffer.from('x')),
    {...fast, connectMs:5, attempts:2, transport:network.transport}), /connection\.exe.*CONNECT_TIMEOUT/)
  assert.equal(network.requests.length, 2)
})
test('SHA256 mismatch is fatal and never retried as a network error', async () => {
  const network = transportFor(() => ({body:Buffer.from('bad')}))
  await assert.rejects(() => verifyHttpsFile(origin + '/updates/hash.exe', record(Buffer.from('yes')),
    {...fast, transport:network.transport}), /CONTENT_MISMATCH/)
  assert.equal(network.requests.length, 1)
})
test('TLS validation and redirects are not bypassed or retried', async () => {
  for (const item of [{error:'CERT_HAS_EXPIRED'}, {status:302, body:Buffer.from('x')}]) {
    const network = transportFor(() => item)
    await assert.rejects(() => verifyHttpsFile(origin + '/updates/security.exe', record(Buffer.from('x')),
      {...fast, transport:network.transport}))
    assert.equal(network.requests.length, 1)
  }
  const network = transportFor(() => ({body:Buffer.from('x')}))
  await assert.rejects(() => verifyHttpsFile('https://other.example/x', record(Buffer.from('x')),
    {...fast, transport:network.transport}), /SOURCE_INVALID/)
  assert.equal(network.requests.length, 0)
})
test('overall deadline bounds even a continuously transferring file', async () => {
  const network = transportFor(() => ({chunks:Array(100).fill(Buffer.from('x')), gap:5}))
  await assert.rejects(() => verifyHttpsFile(origin + '/updates/deadline.exe', record(Buffer.alloc(100, 'x')),
    {...fast, deadlineMs:30, idleMs:100, transport:network.transport}), /TOTAL_TIMEOUT/)
})

test('bridge recovery checks four exact signed policies and the legacy full file without redownloading four channel EXEs', async () => {
  const f = await fixture(false)
  try {
    const bodies = new Map()
    let legacyPolicy
    for (const id of targets) {
      const folder = path.join(f.root, id)
      const report = await inspectArtifacts(folder, {targetId:id, trust:f.trust})
      const payload = makeReleasePayload(report, {sequence:1, minimumVersion:'0.4.2'})
      const payloadBytes = Buffer.from(JSON.stringify(payload))
      const envelope = Buffer.from(JSON.stringify({payload:payloadBytes.toString('base64'),
        signature:crypto.sign(null, payloadBytes, f.privateKey).toString('base64')}))
      fs.writeFileSync(path.join(folder, 'release.json'), envelope)
      bodies.set('/releases/desktop/' + id + '.json', envelope)
      for (const key of ['artifact','blockmap','updaterManifest']) {
        const name = report[key].fileName
        bodies.set('/updates/desktop/' + id + '/' + name, fs.readFileSync(path.join(folder, name)))
        if (id === 'win10-x64') bodies.set('/updates/' + name, fs.readFileSync(path.join(folder, name)))
      }
      if (id === 'win10-x64') legacyPolicy = {schemaVersion:1, desktop:{...payload.desktop,
        downloadUrl:origin + '/updates/' + report.artifact.fileName}}
    }
    const network = transportFor(name => {
      assert.ok(bodies.has(name), 'Unexpected public request ' + name)
      return {body:bodies.get(name)}
    })
    const result = await checkPublic(f.root, targets, {scope:'bridge', transport:network.transport,
      requestJson:async () => legacyPolicy, log:() => {}, transferOptions:fast})
    assert.equal(result.scope, 'bridge')
    assert.equal(result.channelPoliciesVerified, 4)
    assert.equal(result.channelFilesRedownloaded, false)
    assert.equal(result.legacyFilesVerified, 3)
    assert.equal(network.requests.filter(name => name.startsWith('/updates/desktop/')).length, 0)
    assert.equal(network.requests.filter(name => name.startsWith('/updates/')).length, 3)

    // Same-size corruption cannot become successful recovery.
    const corrupt = transportFor(name => ({body:name.endsWith('.exe')
      ? Buffer.alloc(bodies.get(name).length, 7) : bodies.get(name)}))
    await assert.rejects(() => checkPublic(f.root, targets, {scope:'bridge',
      transport:corrupt.transport, requestJson:async () => legacyPolicy, log:() => {}, transferOptions:fast}), /CONTENT_MISMATCH/)
    await assert.rejects(() => checkPublic(f.root, targets, {scope:'bridge',
      transport:network.transport, requestJson:async () => ({...legacyPolicy, desktop:{...legacyPolicy.desktop, latestVersion:'9.9.9'}}),
      log:() => {}, transferOptions:fast}), /LEGACY_POLICY_MISMATCH/)

    const full = await checkPublic(f.root, targets, {scope:'all', transport:network.transport,
      requestJson:async () => legacyPolicy, log:() => {}, transferOptions:fast})
    assert.equal(full.channelFilesRedownloaded, true)
    assert.equal(network.requests.filter(name => name.startsWith('/updates/desktop/')).length, 12)
  } finally { f.close() }
})
