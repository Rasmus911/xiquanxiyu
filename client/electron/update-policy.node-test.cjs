const test = require('node:test')
const assert = require('node:assert/strict')

const {
  compareSemver,
  decideDesktopUpdate,
  normalizeDesktopPolicy,
  parseSemver,
} = require('./update-policy.cjs')

const validPolicy = {
  latestVersion: '0.3.0',
  minimumVersion: '0.2.5',
  required: false,
  downloadUrl: 'https://api.pqxqxy.xyz/updates/Xiquan-Bathhouse-Setup-0.3.0.exe',
  sha256: 'a'.repeat(64),
  releaseNotes: ['更新中心', 123],
  publishedAt: '2026-09-27T12:00:00+08:00',
}

test('parses and compares strict three-part semantic versions', () => {
  assert.deepEqual(parseSemver('1.2.3'), [1, 2, 3])
  assert.equal(parseSemver('1.2'), null)
  assert.equal(parseSemver('1.2.3-beta'), null)
  assert.equal(compareSemver('1.10.0', '1.2.9'), 1)
  assert.equal(compareSemver('1.2.3', '1.2.3'), 0)
})

test('forces versions below minimum', () => {
  assert.equal(decideDesktopUpdate('0.2.3', validPolicy), 'required')
})

test('offers compatible newer versions', () => {
  assert.equal(decideDesktopUpdate('0.2.5', validPolicy), 'optional')
})

test('does not downgrade a newer client', () => {
  assert.equal(decideDesktopUpdate('0.4.0', validPolicy), 'none')
})

test('normalizes a valid desktop policy', () => {
  assert.deepEqual(normalizeDesktopPolicy(validPolicy), {
    latestVersion: '0.3.0',
    minimumVersion: '0.2.5',
    required: false,
    downloadUrl: 'https://api.pqxqxy.xyz/updates/Xiquan-Bathhouse-Setup-0.3.0.exe',
    sha256: 'a'.repeat(64),
    releaseNotes: ['更新中心', '123'],
    publishedAt: '2026-09-27T12:00:00+08:00',
  })
})

test('rejects unsafe or incomplete desktop policy values', () => {
  assert.equal(normalizeDesktopPolicy({ ...validPolicy, downloadUrl: 'http://example.com/update.exe' }), null)
  assert.equal(normalizeDesktopPolicy({ ...validPolicy, sha256: 'ABC' }), null)
  assert.equal(normalizeDesktopPolicy({ ...validPolicy, latestVersion: '0.3' }), null)
})
