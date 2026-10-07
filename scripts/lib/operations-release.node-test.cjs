const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const crypto = require('node:crypto')
const { validateOperationsManifest } = require('./operations-release.cjs')
const { pe } = require('./desktop-release-fixture.cjs')

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiquan-operations-release-test-'))
  function record(file, bytes) {
    fs.mkdirSync(path.dirname(path.join(root, file)), { recursive: true })
    fs.writeFileSync(path.join(root, file), bytes)
    return { file, size: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') }
  }
  const manifest = { schema: 1, source_commit: '1'.repeat(40), desktop_version: '0.4.3',
    android_version: '1.2.2', android_version_code: 9, build_id: 'operations-fixture',
    trust_key_id: 'b26477a9ed540ad0', signature_status: 'not-signed',
    targets: [{ target: 'win11-x64', runtime: '44.5.1', arch: 'x64',
      ...record('win11-x64/Xiquan-Bathhouse-Setup-0.4.3-win11-x64.exe', pe('ia32')) }],
    android: { ...record('xiquan-mobile-ordering-1.2.2.apk', Buffer.from('PK fixture')),
      certificate_status: 'not-verified' },
    source_web: record('xiquan-operations-SOURCE-WEB-fixture.zip', Buffer.from('PK source fixture')),
    test_results: { backend: 'passed', desktop: 'passed', mobile: 'passed', release: 'passed', pg17_restore: 'not-tested' },
    real_device_checks: { windows11: 'not-tested', android: 'not-tested', usb_printer: 'not-tested' } }
  return { root, manifest, close: () => fs.rmSync(root, { recursive: true, force: true }) }
}

test('candidate manifest checks the one actual installer, APK and source hashes while retaining unverified gates', () => {
  const f = fixture()
  try {
    const report = validateOperationsManifest(f.root, f.manifest)
    assert.equal(report.production_ready, false)
    assert.deepEqual(report.targets, ['win11-x64'])
    assert.ok(report.pending.includes('pg17_restore'))
    assert.throws(() => validateOperationsManifest(f.root, f.manifest, { production: true }), /签名|signature|门禁/i)
    fs.appendFileSync(path.join(f.root, f.manifest.targets[0].file), 'changed')
    assert.throws(() => validateOperationsManifest(f.root, f.manifest), /hash|校验|大小/i)
  } finally { f.close() }
})
test('wrong targets, identity, version and escaped or repeated release paths cannot become a delivery', () => {
  const f = fixture()
  try {
    const mutations = [
      m => { m.targets = [] }, m => { m.targets.push({ ...m.targets[0], target: 'win7-x86' }) },
      m => { m.targets[0].arch = 'ia32' }, m => { m.targets[0].runtime = '22.3.27' },
      m => { m.trust_key_id = '0123456789abcdef' }, m => { m.testOnly = true },
      m => { m.desktop_version = '0.4.2' }, m => { m.android_version_code = 8 },
      m => { m.source_commit = 'unknown' }, m => { m.targets[0].file = '../outside.exe' },
      m => { m.source_web.file = m.android.file }, m => { m.android.file = 'C:/outside.apk' },
      m => { m.targets[0].sha256 = '0'.repeat(64) },
    ]
    for (const mutate of mutations) {
      const manifest = structuredClone(f.manifest); mutate(manifest)
      assert.throws(() => validateOperationsManifest(f.root, manifest))
    }
  } finally { f.close() }
})
test('claimed passed flags do not replace inspection of the original signed desktop payload', () => {
  const f = fixture()
  try {
    f.manifest.signature_status = 'verified'
    f.manifest.android.certificate_status = 'verified'
    f.manifest.android.certificate_sha256 = 'a'.repeat(64)
    for (const key of Object.keys(f.manifest.test_results)) f.manifest.test_results[key] = 'passed'
    for (const key of Object.keys(f.manifest.real_device_checks)) f.manifest.real_device_checks[key] = 'passed'
    assert.equal(validateOperationsManifest(f.root, f.manifest).production_ready, false)
    assert.throws(() => validateOperationsManifest(f.root, f.manifest, { production: true }))
  } finally { f.close() }
})
