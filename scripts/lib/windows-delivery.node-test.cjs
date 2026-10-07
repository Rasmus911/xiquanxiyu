const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { fixture } = require('./desktop-release-fixture.cjs')
const { prepareDelivery } = require('./windows-delivery.cjs')
test('explicit Win11 delivery contains one installer and never needs or copies older targets', async () => {
  const f = await fixture()
  try {
    fs.unlinkSync(path.join(f.root, 'win7-x86/latest.yml'))
    const outputRoot = path.join(f.root, 'one-delivery')
    const result = await prepareDelivery({ releaseRoot: f.root, outputRoot, candidate: true, targets: ['win11-x64'] })
    assert.equal(result.index.complete, true)
    assert.deepEqual(result.files.filter(name => name.endsWith('.exe')), ['win11-x64/Xiquan-Bathhouse-Setup-0.4.2-win11-x64.exe'])
    assert.equal(fs.existsSync(path.join(outputRoot, 'win10-x64')), false)
    assert.match(fs.readFileSync(path.join(outputRoot, 'SHA256SUMS'), 'utf8'), /win11-x64/)
    await assert.rejects(() => prepareDelivery({ releaseRoot: f.root, outputRoot: path.join(f.root, 'formal-one'), targets: ['win11-x64'] }), /测试/)
  } finally { f.close() }
})
test('candidate delivery includes six inspected installers, hashes and public identity, never unpacked data or keys', async () => {
  const f = await fixture()
  try {
    const directory = path.join(f.root, 'delivery')
    const result = await prepareDelivery({ releaseRoot: f.root, outputRoot: directory, candidate: true })
    assert.equal(result.index.complete, true); assert.equal(result.index.signed, false)
    assert.equal(result.files.filter(name => name.endsWith('.exe')).length, 6)
    assert.equal(result.files.some(name => /app\.asar|\.env|\.jks|private/i.test(name)), false)
    assert.match(fs.readFileSync(path.join(directory, 'release-public-key.pem'), 'utf8'), /^-----BEGIN PUBLIC KEY-----/)
    await assert.rejects(() => prepareDelivery({ releaseRoot: f.root, outputRoot: path.join(f.root, 'formal') }), /测试/)
    fs.unlinkSync(path.join(f.root, 'win11-x64/latest.yml'))
    await assert.rejects(() => prepareDelivery({ releaseRoot: f.root, outputRoot: path.join(f.root, 'broken'), candidate: true }))
    assert.equal(fs.existsSync(path.join(f.root, 'broken')), false)
  } finally { f.close() }
})
