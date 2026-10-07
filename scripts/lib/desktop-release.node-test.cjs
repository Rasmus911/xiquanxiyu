const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const crypto = require('node:crypto')
const { createRequire } = require('node:module')
const fromClient = createRequire(path.resolve(__dirname, '../../client/package.json'))
const asar = fromClient('@electron/asar')
const yaml = fromClient('js-yaml')
const { getTarget, targetIds } = require('../../client/electron/target-profiles.cjs')
const { peArch, inspectArtifacts, makeReleasePayload, verifyReleaseSet } = require('./desktop-release.cjs')

const { pe, fixture } = require('./desktop-release-fixture.cjs')
test('PE architecture checks application payloads, not the NSIS stub', () => {
  assert.equal(peArch(pe('ia32')), 'ia32'); assert.equal(peArch(pe('x64')), 'x64')
  for (const bytes of [Buffer.from('not an exe'), Buffer.alloc(512)]) assert.throws(() => peArch(bytes))
})
test('an explicit single target is complete without requiring the five unrequested installers', async () => {
  const f = await fixture()
  try {
    fs.unlinkSync(path.join(f.root, 'win7-x86/latest.yml'))
    const result = await verifyReleaseSet(f.root, ['win11-x64'])
    assert.equal(result.complete, true)
    assert.equal(result.allTargets, false)
    assert.deepEqual(result.requestedTargets, ['win11-x64'])
    assert.deepEqual(result.targets.map(row => row.profile.targetId), ['win11-x64'])
    await assert.rejects(() => verifyReleaseSet(f.root))
    await assert.rejects(() => verifyReleaseSet(f.root, ['win11-x64', 'win11-x64']))
    await assert.rejects(() => verifyReleaseSet(f.root, ['not-a-target']))
  } finally { f.close() }
})
test('candidate inspection checks real ASAR identity, payload architecture and installer hashes', async () => {
  const f = await fixture()
  try {
    const report = await inspectArtifacts(path.join(f.root, 'win7-x86'), { targetId: 'win7-x86', trust: f.trust })
    assert.equal(report.profile.electronVersion, '22.3.27'); assert.equal(report.payloadArch, 'ia32')
    assert.equal(report.artifact.size, 512)
    const index = await verifyReleaseSet(f.root, targetIds, { mode: 'candidate', trust: f.trust })
    assert.equal(index.complete, true); assert.equal(index.signed, false)
    assert.equal(index.acceptance.realOs, 'not-tested')
    fs.writeFileSync(path.join(f.root, 'win7-x86', report.artifact.fileName), 'corrupt')
    await assert.rejects(() => verifyReleaseSet(f.root, targetIds, { mode: 'candidate', trust: f.trust }))
  } finally { f.close() }
})
test('all six valid signatures are required for a formal release and test packages never become formal', async () => {
  const f = await fixture(false)
  try {
    for (const id of targetIds) {
      const report = await inspectArtifacts(path.join(f.root, id), { targetId: id, trust: f.trust })
      const payload = makeReleasePayload(report, { sequence: 1, minimumVersion: '0.4.2', releaseNotes: [], publishedAt: new Date().toISOString() })
      const bytes = Buffer.from(JSON.stringify(payload))
      fs.writeFileSync(path.join(f.root, id, 'release.json'), JSON.stringify({ payload: bytes.toString('base64'), signature: crypto.sign(null, bytes, f.privateKey).toString('base64') }))
    }
    assert.equal((await verifyReleaseSet(f.root, targetIds, { mode: 'release', trust: f.trust })).signed, true)
    fs.unlinkSync(path.join(f.root, 'win11-x64/release.json'))
    await assert.rejects(() => verifyReleaseSet(f.root, targetIds, { mode: 'release', trust: f.trust }))
  } finally { f.close() }
  const candidate = await fixture()
  try { await assert.rejects(() => verifyReleaseSet(candidate.root, targetIds, { mode: 'release', trust: candidate.trust }), /测试/ ) }
  finally { candidate.close() }
})

test('an accidentally placed PEM or key file is rejected by name without reading any key contents', async () => {
  const f = await fixture()
  try {
    const source = path.join(f.root, 'fixture-source-win7-x86')
    fs.writeFileSync(path.join(source, 'electron/desktop-release-private.pem'), 'not a key; isolated filename fixture')
    await asar.createPackage(source, path.join(f.root, 'win7-x86/win-ia32-unpacked/resources/app.asar'))
    await assert.rejects(() => inspectArtifacts(path.join(f.root, 'win7-x86'), { targetId: 'win7-x86', trust: f.trust }), /禁止发布/)
  } finally { f.close() }
})
