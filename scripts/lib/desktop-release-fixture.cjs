const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const crypto = require('node:crypto')
const { createRequire } = require('node:module')
const fromClient = createRequire(path.resolve(__dirname, '../../client/package.json'))
const asar = fromClient('@electron/asar')
const yaml = fromClient('js-yaml')
const { getTarget, targetIds } = require('../../client/electron/target-profiles.cjs')
function pe(arch) {
  const bytes = Buffer.alloc(512); bytes.write('MZ'); bytes.writeUInt32LE(128, 0x3c)
  bytes.write('PE\0\0', 128); bytes.writeUInt16LE(arch === 'ia32' ? 0x14c : 0x8664, 132)
  return bytes
}
async function fixture(testOnly = true) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiquan-release-test-'))
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519')
  const trust = { publicKeyPem: publicKey.export({ type: 'spki', format: 'pem' }), testOnly,
    keyId: crypto.createHash('sha256').update(publicKey.export({ type: 'spki', format: 'der' })).digest('hex').slice(0, 16) }
  for (const id of targetIds) {
    const profile = getTarget(id), directory = path.join(root, id), unpacked = path.join(directory, profile.arch === 'ia32' ? 'win-ia32-unpacked' : 'win-unpacked')
    fs.mkdirSync(path.join(unpacked, 'resources'), { recursive: true })
    fs.writeFileSync(path.join(unpacked, '溪泉洗浴管理系统.exe'), pe(profile.arch))
    const source = path.join(root, 'fixture-source-' + id)
    fs.mkdirSync(path.join(source, 'dist'), { recursive: true }); fs.mkdirSync(path.join(source, 'electron'))
    fs.writeFileSync(path.join(source, 'dist/index.html'), '<html></html>')
    for (const name of ['main.cjs', 'preload.cjs', 'target-profiles.cjs', 'updater.cjs']) fs.writeFileSync(path.join(source, 'electron', name), '// fixture')
    fs.writeFileSync(path.join(source, 'package.json'), JSON.stringify({ version: '0.4.2', main: 'electron/main.cjs',
      xiquanDesktop: { schemaVersion: 1, ...profile, buildId: 'fixture-build', releaseTrust: trust } }))
    await asar.createPackage(source, path.join(unpacked, 'resources/app.asar'))
    const name = `Xiquan-Bathhouse-Setup-0.4.2-${id}.exe`, bytes = pe('ia32')
    fs.writeFileSync(path.join(directory, name), bytes); fs.writeFileSync(path.join(directory, name + '.blockmap'), 'fixture-blockmap')
    const hash = crypto.createHash('sha512').update(bytes).digest('base64')
    fs.writeFileSync(path.join(directory, 'latest.yml'), yaml.dump({ version: '0.4.2', files: [{ url: name, sha512: hash, size: bytes.length }], path: name, sha512: hash }))
  }
  return { root, trust, privateKey, close: () => fs.rmSync(root, { recursive: true, force: true }) }
}
module.exports = { pe, fixture }
