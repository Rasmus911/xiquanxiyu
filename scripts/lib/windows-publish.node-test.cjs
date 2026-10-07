const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const crypto = require('node:crypto')
const { fixture } = require('./desktop-release-fixture.cjs')
const { targetIds } = require('../../client/electron/target-profiles.cjs')
const { inspectArtifacts, makeReleasePayload } = require('./desktop-release.cjs')
const { stageWindowsRelease, activationScript } = require('./windows-publish.cjs')

async function signFixture(f) {
  for (const id of targetIds) {
    const report = await inspectArtifacts(path.join(f.root, id), { targetId: id, trust: f.trust })
    const bytes = Buffer.from(JSON.stringify(makeReleasePayload(report, { sequence: 1, minimumVersion: '0.4.2' })))
    fs.writeFileSync(path.join(f.root, id, 'release.json'), JSON.stringify({ payload: bytes.toString('base64'), signature: crypto.sign(null, bytes, f.privateKey).toString('base64') }))
  }
}
test('Win11-only staging has no legacy feed or other platform policy to overwrite', async () => {
  const f = await fixture(false)
  try {
    await signFixture(f)
    fs.unlinkSync(path.join(f.root, 'win7-x86/latest.yml'))
    const outputRoot = path.join(f.root, 'xiquan-windows-one-fixture')
    const result = await stageWindowsRelease({ releaseRoot: f.root, outputRoot, targets: ['win11-x64'] })
    assert.equal(result.index.complete, true)
    assert.equal(fs.existsSync(path.join(outputRoot, 'releases/desktop/win11-x64.json')), true)
    for (const relative of ['updates/latest.yml', 'releases/client-policy.json', 'merge-legacy-policy.py',
      ...targetIds.filter(id => id !== 'win11-x64').map(id => 'releases/desktop/' + id + '.json')]) {
      assert.equal(fs.existsSync(path.join(outputRoot, relative)), false, relative)
    }
    const hashes = fs.readFileSync(path.join(outputRoot, 'SHA256SUMS'), 'utf8')
    assert.match(hashes, /updates\/desktop\/win11-x64\//)
    assert.doesNotMatch(hashes, /win7|win10|win11-x86|client-policy/)
  } finally { f.close() }
})
test('stage verifies six signatures, preserves mobile/web policies, and uses only win10-x64 for the old entry', async () => {
  const f = await fixture(false)
  try {
    await signFixture(f)
    const oldPolicy = { schemaVersion: 1, android: { latestVersion: '1.2.1', extra: 'preserved' }, web: { buildId: 'old-web' }, desktop: {} }
    const outputRoot = path.join(f.root, 'xiquan-windows-fixture')
    const result = await stageWindowsRelease({ releaseRoot: f.root, outputRoot, legacyPolicy: oldPolicy })
    assert.equal(result.index.signed, true)
    const policy = JSON.parse(fs.readFileSync(path.join(outputRoot, 'releases/client-policy.json'), 'utf8'))
    assert.deepEqual(policy.android, oldPolicy.android); assert.deepEqual(policy.web, oldPolicy.web)
    assert.match(policy.desktop.downloadUrl, /updates\/Xiquan-Bathhouse-Setup-0\.4\.2-win10-x64.exe$/)
    for (const id of targetIds) assert.equal(fs.existsSync(path.join(outputRoot, 'releases/desktop', id + '.json')), true)
    assert.equal(fs.existsSync(path.join(outputRoot, 'SHA256SUMS')), true)
    await assert.rejects(() => stageWindowsRelease({ releaseRoot: f.root, outputRoot, legacyPolicy: oldPolicy }), /已存在/)
  } finally { f.close() }
})
test('test-only, missing or modified files stop before a stage directory is created', async () => {
  const f = await fixture()
  try {
    const outputRoot = path.join(f.root, 'stage')
    await assert.rejects(() => stageWindowsRelease({ releaseRoot: f.root, outputRoot, legacyPolicy: {} }), /测试/)
    assert.equal(fs.existsSync(outputRoot), false)
  } finally { f.close() }
})
test('activation parameters cannot inject shell or target broad paths', () => {
  for (const remoteCloudDir of ['/', '/opt', '/opt/../etc', '/opt/test;id']) assert.throws(() => activationScript({ remoteStage: '/tmp/xiquan-windows-fixture', remoteCloudDir }))
  const script = activationScript({ remoteStage: '/tmp/xiquan-windows-fixture', remoteCloudDir: '/opt/xiquan/xiquan/deploy/cloud' })
  assert.ok(script.indexOf('sha256sum -c') < script.indexOf('mv -f'))
  assert.match(script, /client-policy\.json/)
  assert.doesNotMatch(script, /docker|psql|rm -rf/)
})
