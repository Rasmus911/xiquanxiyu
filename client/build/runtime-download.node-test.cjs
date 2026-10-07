const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { getTarget } = require('../electron/target-profiles.cjs')
const { prepareRuntime, offlineRuntimeDownloader } = require('./runtime-download.cjs')
const { spawnSync } = require('node:child_process')
test('all four production runtime tuples verify the official offline bytes', async () => {
  const cache = path.resolve(__dirname, '../../release/runtime-cache/stock-20261005')
  for (const [version, arch] of [['22.3.27','ia32'], ['22.3.27','x64'], ['43.7.7','ia32'], ['44.5.1','x64']]) {
    assert.equal(await offlineRuntimeDownloader(cache)({version, arch, platform:'win32', artifactName:'electron'}),
      path.join(cache, `electron-v${version}-win32-${arch}.zip`))
  }
})
test('explicit offline cache verifies archive bytes and refuses missing, changed or unpinned runtimes without deleting them', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiquan-sdk-offline-test-'))
  try {
    const name = 'electron-v44.5.1-win32-x64.zip', zip = path.join(root, name), bytes = Buffer.from('isolated archive bytes')
    const options = { version: '44.5.1', platform: 'win32', arch: 'x64', artifactName: 'electron' }
    const pins = { '44.5.1-x64': { fileName: name, size: bytes.length,
      sha256: require('node:crypto').createHash('sha256').update(bytes).digest('hex') } }
    const download = offlineRuntimeDownloader(root, pins)
    await assert.rejects(() => download(options), /缓存|cache/i)
    fs.writeFileSync(zip, bytes)
    assert.equal(await download(options), zip)
    fs.writeFileSync(zip, Buffer.from('altered archive bytes'))
    await assert.rejects(() => download(options), /校验|checksum/i)
    assert.equal(fs.existsSync(zip), true)
    await assert.rejects(() => download({ ...options, arch: 'ia32' }), /pin|固定/i)
    assert.throws(() => offlineRuntimeDownloader('relative-cache'), /绝对|absolute/i)
    // The production pin must never accept the small fixture archive.
    await assert.rejects(() => offlineRuntimeDownloader(root)(options), /校验|checksum/i)
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})
test('offline runtime preparation never invokes the ordinary network downloader and records its true checksum source', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiquan-sdk-offline-prepare-test-'))
  try {
    const zip = path.join(root, 'electron-v44.5.1-win32-x64.zip'), bytes = Buffer.from('isolated archive')
    fs.writeFileSync(zip, bytes)
    const downloadArtifact = offlineRuntimeDownloader(root, { '44.5.1-x64': { fileName: path.basename(zip), size: bytes.length,
      sha256: require('node:crypto').createHash('sha256').update(bytes).digest('hex') } })
    const directory = await prepareRuntime(getTarget('win11-x64'), path.join(root, 'runtime'), {
      downloadArtifact, checksumValidation: 'pinned-official-sha256', extractZip: async (_file, { dir }) => {
        fs.mkdirSync(dir, { recursive: true }); fs.writeFileSync(path.join(dir, 'version'), '44.5.1')
        fs.writeFileSync(path.join(dir, 'electron.exe'), require('../../scripts/lib/desktop-release-fixture.cjs').pe('x64'))
      },
    })
    const evidence = JSON.parse(fs.readFileSync(path.join(directory, 'sdk-evidence.json'), 'utf8'))
    assert.equal(evidence.checksumValidation, 'pinned-official-sha256')
    assert.equal(evidence.sha256, 'd44c5b67288e519184d3548f6a860785242e81077c55b03fc9112e7c15479693')
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})
test('runtime preparation extracts directly to an isolated target runtime and checks version and PE architecture', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiquan-sdk-test-')), calls = []
  try {
    const zip = path.join(root, 'electron-v22.3.27-win32-ia32.zip'); fs.writeFileSync(zip, 'fixture')
    const profile = getTarget('win7-x86')
    const directory = await prepareRuntime(profile, path.join(root, 'runtimes'), {
      downloadArtifact: async options => { calls.push(options); return zip },
      extractZip: async (_zip, options) => {
        fs.mkdirSync(options.dir, { recursive: true }); fs.writeFileSync(path.join(options.dir, 'version'), '22.3.27')
        const pe = Buffer.alloc(512); pe.write('MZ'); pe.writeUInt32LE(128, 0x3c); pe.write('PE\0\0', 128); pe.writeUInt16LE(0x14c, 132)
        fs.writeFileSync(path.join(options.dir, 'electron.exe'), pe)
      },
    })
    assert.equal(path.basename(directory), '22.3.27-ia32')
    assert.equal(calls[0].arch, 'ia32'); assert.equal(calls[0].unsafelyDisableChecksums, undefined)
    assert.equal(fs.existsSync(path.join(directory, 'sdk-evidence.json')), true)
    fs.writeFileSync(path.join(directory, 'version'), '44.5.1')
    await assert.rejects(() => prepareRuntime(profile, path.join(root, 'runtimes'), {}), /版本/)
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})

test('real Windows ZIP extraction completes with the installed build Node runtime', { timeout: 15000 }, async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiquan-sdk-zip-test-'))
  try {
    const source = path.join(root, 'source'); fs.mkdirSync(source)
    fs.writeFileSync(path.join(source, 'version'), '22.3.27')
    const pe = require('node:crypto').randomBytes(700000); pe.write('MZ'); pe.writeUInt32LE(128, 0x3c); pe.write('PE\0\0', 128); pe.writeUInt16LE(0x14c, 132)
    fs.writeFileSync(path.join(source, 'electron.exe'), pe)
    const zip = path.join(root, 'electron-v22.3.27-win32-ia32.zip')
    const made = spawnSync('powershell.exe', ['-NoProfile', '-Command', 'Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::CreateFromDirectory($env:XIQUAN_ZIP_SOURCE,$env:XIQUAN_ZIP_TARGET)'],
      { env: { ...process.env, XIQUAN_ZIP_SOURCE: source, XIQUAN_ZIP_TARGET: zip }, encoding: 'utf8', windowsHide: true })
    assert.equal(made.status, 0, made.stderr)
    const directory = await prepareRuntime(getTarget('win7-x86'), path.join(root, 'runtimes'), { downloadArtifact: async () => zip })
    assert.equal(fs.existsSync(path.join(directory, 'electron.exe')), true)
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})
