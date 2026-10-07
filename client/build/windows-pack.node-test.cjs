const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { fixture } = require('../../scripts/lib/desktop-release-fixture.cjs')
const { targetIds } = require('../electron/target-profiles.cjs')
const { buildWindowsRelease } = require('./windows-pack.cjs')
test('the runner rejects a relative offline cache before writing any build output', async () => {
  const f = await fixture()
  try {
    const projectRoot = path.join(f.root, 'project'); fs.mkdirSync(path.join(projectRoot, 'client'), { recursive: true })
    fs.writeFileSync(path.join(projectRoot, 'client/package.json'), '{"version":"0.4.2"}')
    await assert.rejects(() => buildWindowsRelease({ projectRoot, version: '0.4.2', buildId: 'fixture',
      targets: ['win11-x64'], trust: f.trust, offlineRuntimeCache: 'relative-cache', dryRun: true }), /绝对|absolute/i)
    assert.equal(fs.existsSync(path.join(projectRoot, 'release')), false)
  } finally { f.close() }
})

test('six-target runner passes exact architectures/runtimes and builds the renderer only once without mutating package version', async () => {
  const f = await fixture()
  try {
    const projectRoot = path.join(f.root, 'project'); fs.mkdirSync(path.join(projectRoot, 'client'), { recursive: true })
    const packageText = JSON.stringify({ version: '0.4.2' }); fs.writeFileSync(path.join(projectRoot, 'client/package.json'), packageText)
    const calls = []
    const result = await buildWindowsRelease({ projectRoot, version: '0.4.2', buildId: 'fixture-build', trust: f.trust }, {
      buildRenderer: async options => { assert.equal(options.apiBaseUrl, 'https://api.pqxqxy.xyz/api'); calls.push('renderer') },
      buildTarget: async config => { calls.push(config.extraMetadata.xiquanDesktop); fs.cpSync(path.join(f.root, config.extraMetadata.xiquanDesktop.targetId), config.directories.output, { recursive: true }) },
    })
    assert.equal(calls.filter(value => value === 'renderer').length, 1)
    assert.equal(calls.length, 7); assert.equal(result.complete, true)
    assert.equal(calls[1].electronVersion, '22.3.27'); assert.equal(calls[3].electronVersion, '43.7.7'); assert.equal(calls[4].electronVersion, '44.5.1')
    assert.equal(fs.readFileSync(path.join(projectRoot, 'client/package.json'), 'utf8'), packageText)
    await assert.rejects(() => buildWindowsRelease({ projectRoot, version: '0.4.2', buildId: 'fixture-build', trust: f.trust }, {}), /已存在/)
  } finally { f.close() }
})
test('dry-run performs no build/write and a failed target stops the sequence', async () => {
  const f = await fixture()
  try {
    const projectRoot = path.join(f.root, 'project'); fs.mkdirSync(path.join(projectRoot, 'client'), { recursive: true })
    fs.writeFileSync(path.join(projectRoot, 'client/package.json'), '{"version":"0.4.2"}')
    const options = { projectRoot, version: '0.4.2', buildId: 'fixture-build', trust: f.trust }
    const dry = await buildWindowsRelease({ ...options, dryRun: true }, {})
    assert.deepEqual(dry.configs.map(c => c.extraMetadata.xiquanDesktop.targetId), targetIds)
    assert.equal(fs.existsSync(path.join(projectRoot, 'release')), false)
    const calls = []
    await assert.rejects(() => buildWindowsRelease(options, { buildRenderer: async () => {}, buildTarget: async config => { calls.push(config.extraMetadata.xiquanDesktop.targetId); throw new Error('fixture failure') } }), /fixture failure/)
    assert.deepEqual(calls, ['win7-x86'])
  } finally { f.close() }
})
