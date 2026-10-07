const test = require('node:test')
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const { EventEmitter } = require('node:events')
const { Readable } = require('node:stream')
const { verifyHttpsFile } = require('./windows-public-check.cjs')
test('public verification hashes streamed HTTPS content rather than accepting HEAD/200 alone', async () => {
  const bytes = Buffer.from('fixture-public-file'), record = { size: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') }
  const transport = body => (_url, options, callback) => {
    assert.equal(options.rejectUnauthorized, true)
    const request = new EventEmitter(); request.destroy = () => {}; request.setTimeout = () => {}
    request.end = () => queueMicrotask(() => { const response = Readable.from([body]); response.statusCode = 200; callback(response) })
    return request
  }
  assert.equal(await verifyHttpsFile('https://api.pqxqxy.xyz/updates/file.exe', record, transport(bytes)), true)
  await assert.rejects(() => verifyHttpsFile('https://api.pqxqxy.xyz/updates/file.exe', record, transport(Buffer.from('wrong'))), /校验/)
  await assert.rejects(() => verifyHttpsFile('http://api.pqxqxy.xyz/file', record, transport(bytes)), /来源/)
})
