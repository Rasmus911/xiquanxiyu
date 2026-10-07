const test = require('node:test')
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const { getTarget, targetIds, detectWindowsFamily, assertHost, assertPackagedTarget, normalizeReleaseTrust } = require('./target-profiles.cjs')

function trust() {
  const { publicKey } = crypto.generateKeyPairSync('ed25519')
  const publicKeyPem = publicKey.export({ type: 'spki', format: 'pem' })
  const keyId = crypto.createHash('sha256').update(publicKey.export({ type: 'spki', format: 'der' })).digest('hex').slice(0, 16)
  return { keyId, publicKeyPem, testOnly: true }
}

test('six build profiles never request an unavailable runtime architecture', () => {
  const cases = [
    ['win7-x86', 'ia32', '22.3.27', ['win7']],
    ['win7-x64', 'x64', '22.3.27', ['win7']],
    ['win10-x86', 'ia32', '43.7.7', ['win10', 'win11']],
    ['win10-x64', 'x64', '44.5.1', ['win10', 'win11']],
    ['win11-x86', 'ia32', '43.7.7', ['win11']],
    ['win11-x64', 'x64', '44.5.1', ['win11']],
  ]
  assert.equal(targetIds.length, 6)
  for (const [id, arch, version, hosts] of cases) {
    const profile = getTarget(id)
    assert.equal(profile.arch, arch)
    assert.equal(profile.electronVersion, version)
    assert.deepEqual(profile.allowedHosts, hosts)
    assert.equal(Object.isFrozen(profile), true)
    assert.equal(Object.isFrozen(profile.allowedHosts), true)
  }
  for (const value of ['../win7-x86', '__proto__', 'win11-arm64', '', null]) assert.throws(() => getTarget(value))
})

test('detects Win7 SP1 and differentiates Win11 by its build', () => {
  for (const [release, expected] of [
    ['6.1.7601', 'win7'], ['6.1.7600', null], ['6.3.9600', null],
    ['10.0.10240', 'win10'], ['10.0.19045', 'win10'],
    ['10.0.22000', 'win11'], ['10.0.26100.1', 'win11'],
    ['garbage', null], ['10.0.NaN', null], ['', null], ['11.0.1', null],
  ]) assert.equal(detectWindowsFamily(release), expected, release)
})

test('Win10 profile remains valid on Win11 but dedicated profiles do not cross families', () => {
  assert.doesNotThrow(() => assertHost(getTarget('win10-x86'), { platform: 'win32', arch: 'ia32', release: '10.0.26100' }))
  assert.doesNotThrow(() => assertHost(getTarget('win11-x64'), { platform: 'win32', arch: 'x64', release: '10.0.26100' }))
  for (const [id, host] of [
    ['win7-x64', { platform: 'win32', arch: 'x64', release: '6.1.7600' }],
    ['win7-x64', { platform: 'win32', arch: 'x64', release: '10.0.26100' }],
    ['win11-x86', { platform: 'win32', arch: 'ia32', release: '10.0.19045' }],
    ['win10-x64', { platform: 'win32', arch: 'ia32', release: '10.0.19045' }],
    ['win10-x64', { platform: 'linux', arch: 'x64', release: '10.0.19045' }],
  ]) assert.throws(() => assertHost(getTarget(id), host), /不匹配/)
})

test('packaged metadata cannot select another runtime or silently omit its identity', () => {
  const profile = getTarget('win7-x86')
  const metadata = { schemaVersion: 1, ...profile, buildId: 'fixture-042', releaseTrust: trust() }
  const runtime = { platform: 'win32', arch: 'ia32', release: '6.1.7601', electronVersion: '22.3.27' }
  const result = assertPackagedTarget(metadata, runtime)
  assert.equal(result.buildId, 'fixture-042')
  assert.equal(result.releaseTrust.testOnly, true)
  for (const change of [
    { schemaVersion: 2 }, { arch: 'x64' }, { electronVersion: '44.5.1' },
    { buildId: '' }, { buildId: '../other' }, { allowedHosts: ['win7', 'win10'] },
    { runtimeFamily: 'windows-x64' }, { releaseTrust: null },
  ]) assert.throws(() => assertPackagedTarget({ ...metadata, ...change }, runtime))
  assert.throws(() => assertPackagedTarget(metadata, { ...runtime, electronVersion: '44.5.1' }))
  assert.throws(() => assertPackagedTarget(null, runtime))
})

test('release trust is a validated public key and explicit test mode, never a private key', () => {
  const valid = trust()
  assert.equal(normalizeReleaseTrust(valid).keyId, valid.keyId)
  for (const change of [{ keyId: 'bad' }, { publicKeyPem: 'bad' }, { testOnly: 'false' }, { testOnly: undefined }]) {
    assert.throws(() => normalizeReleaseTrust({ ...valid, ...change }))
  }
  const { privateKey } = crypto.generateKeyPairSync('ed25519')
  assert.throws(() => normalizeReleaseTrust({ ...valid, publicKeyPem: privateKey.export({ type: 'pkcs8', format: 'pem' }) }))
})
