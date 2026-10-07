const test = require('node:test')
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const { generateReleaseKey, signReleasePayload } = require('./desktop-signing.cjs')
const { fixture } = require('./desktop-release-fixture.cjs')
const { verifyReleaseSet } = require('./desktop-release.cjs')
const { targetIds } = require('../../client/electron/target-profiles.cjs')

test('stdin signing with an explicit Win11 target leaves all five old policies untouched', async () => {
  const f = await fixture(false)
  try {
    const passphrase = 'isolated-fixture-passphrase-123'
    const privatePath = path.join(f.root, 'fixture-private.pem')
    fs.writeFileSync(path.join(f.root, 'release-public-key.pem'), f.trust.publicKeyPem)
    fs.writeFileSync(privatePath, f.privateKey.export({ type: 'pkcs8', format: 'pem', cipher: 'aes-256-cbc', passphrase }))
    fs.unlinkSync(path.join(f.root, 'win7-x86/latest.yml'))
    const oldFiles = targetIds.filter(id => id !== 'win11-x64').map(id => [id,
      fs.readFileSync(path.join(f.root, id, `Xiquan-Bathhouse-Setup-0.4.2-${id}.exe`))])
    const signed = spawnSync(process.execPath, [path.join(__dirname, 'desktop-signing.cjs')], { input: JSON.stringify({
      action: 'sign', releaseRoot: f.root, privatePath, passphrase, sequence: 8, minimumVersion: '0.4.2', targets: ['win11-x64'],
    }), encoding: 'utf8', windowsHide: true, timeout: 30000 })
    assert.equal(signed.status, 0, signed.stderr)
    const result = await verifyReleaseSet(f.root, ['win11-x64'], { mode: 'release', trust: f.trust })
    assert.equal(result.complete, true)
    for (const [id, bytes] of oldFiles) {
      assert.equal(fs.existsSync(path.join(f.root, id, 'release.json')), false)
      assert.deepEqual(fs.readFileSync(path.join(f.root, id, `Xiquan-Bathhouse-Setup-0.4.2-${id}.exe`)), bytes)
    }
    assert.doesNotMatch(signed.stdout + signed.stderr, /isolated-fixture-passphrase/)
  } finally { f.close() }
})

test('release keys are encrypted Ed25519 and correct hidden passwords are required', () => {
  const keys = generateReleaseKey('fixture-passphrase-123')
  assert.match(keys.privateKeyPem, /BEGIN ENCRYPTED PRIVATE KEY/)
  assert.match(keys.publicKeyPem, /BEGIN PUBLIC KEY/)
  const payload = { keyId: keys.keyId, schemaVersion: 2, sequence: 1 }
  const envelope = signReleasePayload(payload, keys.privateKeyPem, 'fixture-passphrase-123', keys.publicKeyPem)
  assert.equal(crypto.verify(null, Buffer.from(envelope.payload, 'base64'), keys.publicKeyPem, Buffer.from(envelope.signature, 'base64')), true)
  assert.throws(() => signReleasePayload(payload, keys.privateKeyPem, 'wrong-password', keys.publicKeyPem), /密码/)
  const other = generateReleaseKey('another-fixture-123')
  assert.throws(() => signReleasePayload(payload, keys.privateKeyPem, 'fixture-passphrase-123', other.publicKeyPem), /不匹配/)
  assert.throws(() => generateReleaseKey('123456789012345'), /16/)
})

test('the actual stdin signing CLI rejects a wrong password, signs all six fixtures and refuses overwrite', async () => {
  const f = await fixture(false)
  try {
    const publicPath = path.join(f.root, 'release-public-key.pem')
    const privatePath = path.join(f.root, 'fixture-private.pem')
    const passphrase = 'fixture-password-not-a-user-key-123'
    fs.writeFileSync(publicPath, f.trust.publicKeyPem)
    fs.writeFileSync(privatePath, f.privateKey.export({ type: 'pkcs8', format: 'pem', cipher: 'aes-256-cbc', passphrase }))
    const input = { action: 'sign', releaseRoot: f.root, privatePath, passphrase, sequence: 1,
      minimumVersion: '0.4.2', releaseNotes: ['isolated signing fixture'] }
    const run = patch => spawnSync(process.execPath, [path.join(__dirname, 'desktop-signing.cjs')],
      { input: JSON.stringify({ ...input, ...patch }), encoding: 'utf8', windowsHide: true, timeout: 30000 })
    const wrong = run({ passphrase: 'incorrect-fixture-password' })
    assert.equal(wrong.status, 1)
    assert.match(wrong.stderr, /密码错误/)
    for (const id of targetIds) assert.equal(fs.existsSync(path.join(f.root, id, 'release.json')), false)
    const signed = run({})
    assert.equal(signed.status, 0, signed.stderr)
    assert.doesNotMatch(signed.stdout + signed.stderr, /fixture-password-not-a-user-key/)
    const index = await verifyReleaseSet(f.root, targetIds, { mode: 'release', trust: f.trust })
    assert.equal(index.complete, true); assert.equal(index.signed, true)
    const original = fs.readFileSync(path.join(f.root, 'win7-x86/release.json'))
    const repeated = run({})
    assert.equal(repeated.status, 1)
    assert.match(repeated.stderr, /不会覆盖/)
    assert.deepEqual(fs.readFileSync(path.join(f.root, 'win7-x86/release.json')), original)
  } finally { f.close() }
})
