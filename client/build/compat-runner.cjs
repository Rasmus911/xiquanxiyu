const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
function runCompatibilitySmoke(root, spawn = spawnSync) {
  const results = []
  for (const runtime of ['22.3.27-ia32', '22.3.27-x64', '43.7.7-ia32', '44.5.1-x64']) {
    const executable = path.join(root, 'runtimes', runtime, 'electron.exe')
    if (!fs.existsSync(executable)) throw new Error('缺少已验证的运行环境')
    const [version, arch] = runtime.split('-')
    const samples = []
    for (const mode of ['node', 'adapter']) {
      const env = { ...process.env }; delete env.ELECTRON_RUN_AS_NODE
      if (mode === 'node') env.ELECTRON_RUN_AS_NODE = '1'
      const file = path.join(__dirname, mode === 'node' ? 'compat-smoke.cjs' : 'electron-compat-smoke.cjs')
      const result = spawn(executable, [file, '--compat-smoke'], { env, encoding: 'utf8', windowsHide: true, timeout: 60000 })
      if (result.error || result.status !== 0) throw new Error(`运行库检查失败：${runtime}/${mode}；${String(result.stderr || '').slice(0, 1200)}`)
      let report
      for (const line of String(result.stdout || '').split(/\r?\n/)) {
        try { const item = JSON.parse(line); if (item.passed === true) report = item } catch { /* Ignore runtime diagnostics. */ }
      }
      if (!report || report.electron !== version || report.arch !== arch || report.network !== false || report.installed !== false ||
          (mode === 'adapter' && (!report.bridge || !report.sandbox))) throw new Error(`缺少有效运行库验收证据：${runtime}/${mode}`)
      samples.push({ mode, ...report })
      console.log(`${runtime}/${mode}: passed`)
    }
    results.push({ runtime, samples, realTargetOs: 'not-tested' })
  }
  const evidence = { schemaVersion: 1, measuredAt: new Date().toISOString(), results, network: false, installed: false }
  fs.writeFileSync(path.join(root, 'runtime-smoke.json'), JSON.stringify(evidence, null, 2), 'utf8')
  return evidence
}
if (require.main === module) {
  try { console.log(JSON.stringify(runCompatibilitySmoke(fs.realpathSync(process.argv[2])), null, 2)) }
  catch (error) { console.error(error.message); process.exitCode = 1 }
}
module.exports = { runCompatibilitySmoke }
