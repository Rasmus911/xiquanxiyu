const test = require('node:test')
const assert = require('node:assert/strict')
const crypto = require('node:crypto')
const path = require('node:path')
const { makeWindowsConfig } = require('./windows-config.cjs')

function options(targetId = 'win7-x86') {
  const { publicKey } = crypto.generateKeyPairSync('ed25519')
  const publicKeyPem = publicKey.export({ type: 'spki', format: 'pem' })
  const keyId = crypto.createHash('sha256').update(publicKey.export({ type: 'spki', format: 'der' })).digest('hex').slice(0, 16)
  return { projectRoot: path.resolve('fixture'), version: '0.4.2', buildId: 'fixture-042', targetId, trust: { keyId, publicKeyPem, testOnly: true } }
}

test('legacy build uses its own runtime/output/feed while preserving the installation identity', () => {
  const opts = options()
  const config = makeWindowsConfig(opts)
  assert.equal(config.electronVersion, '22.3.27')
  assert.equal(config.electronDist, undefined)
  assert.deepEqual(config.win.target, [{ target: 'nsis', arch: ['ia32'] }])
  assert.equal(config.appId, 'com.xiquan.bathhouse')
  assert.equal(config.artifactName, 'Xiquan-Bathhouse-Setup-${version}-win7-x86.${ext}')
  assert.equal(config.extraMetadata.version, '0.4.2')
  assert.equal(config.extraMetadata.xiquanDesktop.targetId, 'win7-x86')
  assert.equal(config.extraMetadata.xiquanDesktop.buildId, 'fixture-042')
  assert.equal(config.extraMetadata.xiquanDesktop.releaseTrust.testOnly, true)
  assert.equal(config.publish.url, 'https://api.pqxqxy.xyz/updates/desktop/win7-x86/')
  assert.equal(config.directories.output, path.join(opts.projectRoot, 'release/windows/0.4.2/fixture-042/win7-x86'))
  assert.equal(config.nsis.include, path.join(opts.projectRoot, 'release/windows/0.4.2/fixture-042/configs/win7-x86.nsh'))
  assert.equal(config.nsis.deleteAppDataOnUninstall, false)
})

test('six targets produce distinct payload architectures and paths without mutating input', () => {
  const pairs = [['win7-x86','ia32','22.3.27'],['win7-x64','x64','22.3.27'],
    ['win10-x86','ia32','43.7.7'],['win10-x64','x64','44.5.1'],
    ['win11-x86','ia32','43.7.7'],['win11-x64','x64','44.5.1']]
  const roots = new Set()
  for (const [id, arch, runtime] of pairs) {
    const opts = options(id)
    const original = JSON.stringify(opts)
    const config = makeWindowsConfig(opts)
    assert.equal(config.electronVersion, runtime)
    assert.deepEqual(config.win.target[0].arch, [arch])
    assert.equal(config.publish.url, `https://api.pqxqxy.xyz/updates/desktop/${id}/`)
    roots.add(config.directories.output)
    assert.equal(JSON.stringify(opts), original)
  }
  assert.equal(roots.size, 6)
})

test('untrusted version/build paths and missing public trust cannot become build configurations', () => {
  for (const patch of [{ version:'latest' },{ version:'../0.4.2' },{ buildId:'../other' },{ buildId:'' },{ targetId:'__proto__' },{ trust:null }]) {
    assert.throws(() => makeWindowsConfig({ ...options(), ...patch }))
  }
})

test('the installed builder resolves a valid per-target feed without merging array indices into publish', async () => {
  const { getConfig, validateConfiguration } = require('app-builder-lib/out/util/config/config')
  const { log } = require('builder-util')
  // Keep the builder's raw logging off the parallel Node test runner's stdout protocol.
  const originalStream = log.stream
  log.stream = process.stderr
  const config = makeWindowsConfig({ ...options(), projectRoot: path.resolve(__dirname, '../..') })
  try {
    const resolved = await getConfig(path.resolve(__dirname, '..'), null, config)
    await validateConfiguration(resolved, { isEnabled: false })
    assert.equal(resolved.publish[0].url, 'https://api.pqxqxy.xyz/updates/desktop/win7-x86/')
    assert.equal(resolved.publish[0]['0'], undefined)
  } finally { log.stream = originalStream }
})
