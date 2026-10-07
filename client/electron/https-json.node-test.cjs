const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { Readable } = require('node:stream')
const { requestHttpsBuffer, requestHttpsJson } = require('./https-json.cjs')
const origin = 'https://api.pqxqxy.xyz'
const url = `${origin}/releases/desktop/win7-x86.json`

function transport({ body = Buffer.from('{"ok":true}'), status = 200, error, hang = false, truncated = false } = {}) {
  const record = { calls: 0, destroyed: false }
  record.request = (requestedUrl, options, callback) => {
    record.calls++
    record.url = String(requestedUrl)
    record.options = options
    const req = new EventEmitter()
    req.destroy = () => { record.destroyed = true }
    req.end = () => {
      if (hang) return
      queueMicrotask(() => {
        if (error) return req.emit('error', error)
        const response = new Readable({ read() {} })
        response.statusCode = status
        response.headers = {}
        callback(response)
        response.push(body)
        if (truncated) response.emit('aborted')
        else response.push(null)
      })
    }
    return req
  }
  return record
}

test('valid JSON and BOM use TLS verification and do not require fetch', async () => {
  for (const body of ['{"ok":true}', '\uFEFF{"ok":true}']) {
    const fixture = transport({ body: Buffer.from(body) })
    assert.deepEqual(await requestHttpsJson(url, { allowedOrigin: origin, request: fixture.request }), { ok: true })
    assert.equal(fixture.options.rejectUnauthorized, true)
    assert.equal(fixture.options.method, 'GET')
  }
})

test('HTTP/foreign origin/URL credentials/fragments fail before any transport', async () => {
  const fixture = transport()
  for (const invalid of ['http://api.pqxqxy.xyz/a','https://evil.invalid/a','https://u:p@api.pqxqxy.xyz/a',`${url}#bad`]) {
    await assert.rejects(requestHttpsJson(invalid, { allowedOrigin: origin, request: fixture.request }))
  }
  assert.equal(fixture.calls, 0)
})

test('HTTP errors and redirects never deliver a policy', async () => {
  for (const status of [301, 302, 307, 404, 502]) {
    const fixture = transport({ status })
    await assert.rejects(requestHttpsJson(url, { allowedOrigin: origin, request: fixture.request }), /HTTP/)
    assert.equal(fixture.destroyed, true)
  }
})

test('certificate and network failures are sanitized without leaking requested URLs or credentials', async () => {
  for (const code of ['CERT_HAS_EXPIRED', 'ENOTFOUND', 'ECONNRESET']) {
    const error = Object.assign(new Error('private diagnostic https://u:p@host'), { code })
    const fixture = transport({ error })
    await assert.rejects(requestHttpsJson(url, { allowedOrigin: origin, request: fixture.request }), err => {
      assert.equal(err.message.includes('u:p'), false)
      return /请求失败/.test(err.message)
    })
  }
})

test('timeout destroys the request and incomplete responses are rejected', async () => {
  const timeout = transport({ hang: true })
  await assert.rejects(requestHttpsJson(url, { allowedOrigin: origin, timeoutMs: 15, request: timeout.request }), /超时/)
  assert.equal(timeout.destroyed, true)
  const fixture = transport({ truncated: true })
  await assert.rejects(requestHttpsJson(url, { allowedOrigin: origin, request: fixture.request }), /不完整/)
})

test('oversized bodies and invalid JSON cannot be accepted', async () => {
  const large = transport({ body: Buffer.alloc(1025) })
  await assert.rejects(requestHttpsBuffer(url, { allowedOrigin: origin, maxBytes: 1024, request: large.request }), /大小/)
  assert.equal(large.destroyed, true)
  for (const body of ['', '<html>502</html>', '{']) {
    await assert.rejects(requestHttpsJson(url, { allowedOrigin: origin, request: transport({ body: Buffer.from(body) }).request }), /格式/)
  }
})

test('construction errors and invalid limits reject predictably', async () => {
  await assert.rejects(requestHttpsBuffer(url, { allowedOrigin: origin, request: () => { throw Error('secret') } }), /请求失败/)
  for (const maxBytes of [0, -1, Infinity]) await assert.rejects(requestHttpsBuffer(url, { allowedOrigin: origin, maxBytes }))
})
