const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { runCompatibilitySmoke } = require('./compat-runner.cjs')
test('smoke runner waits for each real process result and requires explicit runtime/arch/bridge evidence', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiquan-smoke-runner-')), calls = []
  try {
    for (const runtime of ['22.3.27-ia32','22.3.27-x64','43.7.7-ia32','44.5.1-x64']) {
      fs.mkdirSync(path.join(root, 'runtimes', runtime), { recursive: true }); fs.writeFileSync(path.join(root, 'runtimes', runtime, 'electron.exe'), 'fixture')
    }
    const spawn = (file, args, options) => {
      calls.push(options.env.ELECTRON_RUN_AS_NODE)
      const runtime = path.basename(path.dirname(file)), [electron, arch] = runtime.split('-')
      return { status: 0, stdout: JSON.stringify({ passed: true, electron, arch, bridge: true, sandbox: true, network: false, installed: false }), stderr: '' }
    }
    const result = runCompatibilitySmoke(root, spawn)
    assert.equal(result.results.length, 4); assert.equal(calls.length, 8)
    assert.equal(calls[0], '1'); assert.equal(calls[1], undefined)
    assert.throws(() => runCompatibilitySmoke(root, () => ({ status: 0, stdout: '' })), /证据/)
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})
