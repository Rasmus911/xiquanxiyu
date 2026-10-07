const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const { fixture } = require('../lib/desktop-release-fixture.cjs')
const { targetIds } = require('../../client/electron/target-profiles.cjs')
async function create() {
  const f = await fixture(process.argv.includes('--candidate'))
  const releaseRoot = path.join(f.root, 'release'); fs.mkdirSync(releaseRoot)
  for (const id of targetIds) fs.cpSync(path.join(f.root, id), path.join(releaseRoot, id), { recursive: true })
  fs.writeFileSync(path.join(releaseRoot, 'release-public-key.pem'), f.trust.publicKeyPem)
  const privatePath = path.join(f.root, 'fixture-private.pem')
  fs.writeFileSync(privatePath, f.privateKey.export({ type: 'pkcs8', format: 'pem', cipher: 'aes-256-cbc', passphrase: 'fixture-password-123' }))
  if (process.argv.includes('--signed')) {
    const signed = spawnSync(process.execPath, [path.resolve(__dirname, '../lib/desktop-signing.cjs')],
      { input: JSON.stringify({ action: 'sign', releaseRoot, privatePath, passphrase: 'fixture-password-123',
        sequence: 1, minimumVersion: '0.4.2', releaseNotes: ['isolated fixture'] }), encoding: 'utf8', windowsHide: true, timeout: 30000 })
    if (signed.error || signed.status !== 0) throw new Error('Fixture signing failed: ' + signed.stderr)
  }
  console.log(JSON.stringify({ fixtureRoot: f.root, releaseRoot, privatePath }))
}
create().catch(error => { console.error(error.message); process.exitCode = 1 })
