const test = require('node:test')
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const fs = require('node:fs/promises')
const path = require('node:path')
const os = require('node:os')
const { getTarget } = require('./target-profiles.cjs')
const { verifySignedRelease, assertUpdaterInfo, verifyDownloadedArtifact } = require('./desktop-release.cjs')

function fixture(targetId = 'win7-x86') {
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519')
  const publicKeyPem = publicKey.export({ type: 'spki', format: 'pem' })
  const keyId = crypto.createHash('sha256').update(publicKey.export({ type: 'spki', format: 'der' })).digest('hex').slice(0,16)
  const trust = { keyId, publicKeyPem, testOnly: false }
  const profile = getTarget(targetId)
  const bytes = Buffer.from('installer-fixture')
  const sha256 = crypto.createHash('sha256').update(bytes).digest('hex')
  const sha512 = crypto.createHash('sha512').update(bytes).digest('base64')
  const fileName = `Xiquan-Bathhouse-Setup-0.4.3-${targetId}.exe`
  const payload = {
    schemaVersion:2, keyId, sequence:5, buildId:'fixture-043', ...profile,
    desktop:{ latestVersion:'0.4.3', minimumVersion:'0.4.2', required:false,
      downloadUrl:`https://api.pqxqxy.xyz/updates/desktop/${targetId}/${fileName}`,
      sha256, releaseNotes:['兼容更新'], publishedAt:'2026-10-03T00:00:00.000Z' },
    artifact:{ fileName, size:bytes.length, sha256, sha512 },
    blockmap:{ fileName:`${fileName}.blockmap`, size:15, sha256:'b'.repeat(64) },
    updaterManifest:{ fileName:'latest.yml', sha256:'c'.repeat(64) },
  }
  function envelope(value = payload) {
    const body = Buffer.from(JSON.stringify(value))
    return { payload:body.toString('base64'), signature:crypto.sign(null,body,privateKey).toString('base64') }
  }
  const context = { trust, profile, currentVersion:'0.4.2', now:new Date('2026-10-03T12:00:00Z'), lastSequence:0 }
  return { payload, envelope, context, bytes }
}

test('valid signed release binds version, target, runtime, artifact and policy sequence', () => {
  const value = fixture()
  const release = verifySignedRelease(value.envelope(), value.context)
  assert.equal(release.profile.targetId, 'win7-x86')
  assert.equal(release.desktop.latestVersion, '0.4.3')
  assert.equal(release.artifact.fileName, 'Xiquan-Bathhouse-Setup-0.4.3-win7-x86.exe')
  assert.equal(release.sequence, 5)
  assert.match(release.payloadHash, /^[0-9a-f]{64}$/)
})

test('changing bytes or signing with another key is rejected', () => {
  const value = fixture()
  const bad = value.envelope()
  bad.payload = Buffer.from(JSON.stringify({ ...value.payload, sequence:6 })).toString('base64')
  assert.throws(() => verifySignedRelease(bad, value.context), /签名/)
  assert.throws(() => verifySignedRelease(fixture().envelope(), value.context), /签名/)
  for (const change of [{ signature:'bad' }, { payload:'bad' }, { payload:'a'.repeat(400000) }]) {
    assert.throws(() => verifySignedRelease({ ...value.envelope(), ...change }, value.context))
  }
})

test('even a signed contradictory target or runtime is rejected', () => {
  const value = fixture()
  for (const patch of [{ targetId:'win10-x64' },{ arch:'x64' },{ allowedHosts:['win7','win10'] },
    { electronVersion:'44.5.1' },{ runtimeFamily:'windows-x64' },{ schemaVersion:1 },{ keyId:'other' },{ buildId:'../bad' }]) {
    assert.throws(() => verifySignedRelease(value.envelope({ ...value.payload, ...patch }), value.context))
  }
  const newerPatch = { ...value.payload, electronVersion:'22.3.28' }
  assert.equal(verifySignedRelease(value.envelope(newerPatch), value.context).electronVersion, '22.3.28')
})

test('signed URLs, artifact names and hashes cannot escape the target directory', () => {
  const value = fixture()
  for (const patch of [{ downloadUrl:'http://api.pqxqxy.xyz/updates/a.exe' },
    { downloadUrl:'https://evil.invalid/a.exe' },{ downloadUrl:`${value.payload.desktop.downloadUrl}?bad` },
    { sha256:'d'.repeat(64) },{ required:'false' },{ minimumVersion:'0.4.4' }]) {
    assert.throws(() => verifySignedRelease(value.envelope({ ...value.payload, desktop:{ ...value.payload.desktop, ...patch } }), value.context))
  }
  for (const patch of [{ fileName:'../a.exe' },{ fileName:'other.exe' },{ size:0 },{ sha512:'bad' }]) {
    assert.throws(() => verifySignedRelease(value.envelope({ ...value.payload, artifact:{ ...value.payload.artifact, ...patch } }), value.context))
  }
  assert.throws(() => verifySignedRelease(value.envelope({ ...value.payload, updaterManifest:{fileName:'other.yml',sha256:'c'.repeat(64)} }), value.context))
})

test('rollback and sequence collisions fail, identical rechecks succeed', () => {
  const value = fixture()
  const result = verifySignedRelease(value.envelope(), value.context)
  assert.throws(() => verifySignedRelease(value.envelope(), { ...value.context, lastSequence:6 }))
  const accepted = { ...value.context, lastSequence:5, lastPayloadHash:result.payloadHash }
  assert.equal(verifySignedRelease(value.envelope(), accepted).sequence, 5)
  assert.throws(() => verifySignedRelease(value.envelope({ ...value.payload, buildId:'other-043' }), accepted))
  assert.throws(() => verifySignedRelease(value.envelope(), { ...value.context, currentVersion:'0.4.4' }))
  assert.throws(() => verifySignedRelease(value.envelope(), { ...value.context, trust:{ ...value.context.trust, testOnly:true } }))
})

test('electron-updater info must describe exactly the signed executable', () => {
  const value = fixture()
  const release = verifySignedRelease(value.envelope(), value.context)
  const file = { url:release.artifact.fileName, sha512:release.artifact.sha512, size:release.artifact.size }
  const info = { version:'0.4.3', files:[file], path:file.url, sha512:file.sha512 }
  assert.doesNotThrow(() => assertUpdaterInfo(info,release))
  for (const patch of [{ version:'0.4.4' },{ files:[file,file] },{ files:[{...file,url:'https://evil.invalid/a.exe'}] },
    { files:[{...file,sha512:'bad'}] },{ files:[{...file,size:2}] },{ packages:{ia32:{file:'web-installer'}} }]) {
    assert.throws(() => assertUpdaterInfo({ ...info, ...patch }, release))
  }
})

test('download content is independently streamed and checked before installation', async () => {
  const value = fixture()
  const release = verifySignedRelease(value.envelope(), value.context)
  const directory = await fs.mkdtemp(path.join(os.tmpdir(),'xiquan-artifact-test-'))
  const file = path.join(directory,'candidate.exe')
  try {
    await fs.writeFile(file,value.bytes)
    await verifyDownloadedArtifact(file,release)
    await fs.writeFile(file,Buffer.from('modified-fixture!'))
    await assert.rejects(verifyDownloadedArtifact(file,release), /校验/)
    await assert.rejects(verifyDownloadedArtifact(directory,release))
  } finally { await fs.rm(directory,{recursive:true,force:true}) }
})
