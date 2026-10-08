const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')

// Only reviewed source areas. Never traverse the project recursively.
const TREES = ['server/app', 'server/migrations', 'server/tests', 'client/src',
  'client/electron', 'client/build', 'mobile/src', 'mobile/public',
  'mobile/android/app/src/main/java', 'mobile/android/app/src/main/res',
  'mobile/android/app/src/test/java', 'mobile/android/app/src/androidTest/java',
  'docs/superpowers', 'docs/releases']
const FILES = new Set([
  ...['build-desktop-049.ps1','sign-desktop-049.ps1','invoke-desktop-049.ps1',
    'desktop-049-deploy-entry.ps1','desktop-049-publish-entry.ps1','desktop-049-android-entry.ps1'].map(file => `scripts/${file}`),
  ...['desktop_049_guard.py','desktop_049_deploy.py','android_127_publication.py'].map(file => `deploy/cloud/scripts/${file}`),
  ...['test_desktop_049_guard.py','test_desktop_049_source.py','test_desktop_049_entrypoints.py',
    'test_android_127_publication.py'].map(file => `scripts/tests/${file}`),
  'scripts/build-desktop-048.ps1', 'scripts/sign-desktop-048.ps1',
  'scripts/desktop-048-deploy-entry.ps1', 'scripts/desktop-048-publish-entry.ps1',
  'scripts/desktop-048-android-entry.ps1', 'scripts/invoke-desktop-048.ps1',
  'deploy/cloud/scripts/desktop_048_guard.py', 'deploy/cloud/scripts/desktop_048_deploy.py',
  'deploy/cloud/scripts/android_126_publication.py',
  'scripts/tests/test_desktop_048_guard.py', 'scripts/tests/test_desktop_048_memory.py',
  'scripts/tests/test_desktop_048_source.py', 'scripts/tests/test_desktop_048_entrypoints.py',
  'scripts/tests/test_android_126_publication.py',
  'scripts/build-desktop-047.ps1', 'scripts/sign-desktop-047.ps1',
  'scripts/desktop-047-deploy-entry.ps1', 'scripts/desktop-047-publish-entry.ps1',
  'scripts/desktop-047-android-entry.ps1', 'scripts/invoke-desktop-047.ps1',
  'deploy/cloud/scripts/desktop_047_guard.py', 'deploy/cloud/scripts/desktop_047_deploy.py',
  'deploy/cloud/scripts/android_125_publication.py',
  'scripts/tests/test_desktop_047_guard.py', 'scripts/tests/test_android_125_publication.py',
  'scripts/tests/test_desktop_047_memory.py',
  'scripts/build-desktop-046.ps1', 'scripts/sign-desktop-046.ps1',
  'scripts/desktop-046-deploy-entry.ps1', 'scripts/desktop-046-publish-entry.ps1',
  'scripts/desktop-046-android-entry.ps1', 'scripts/invoke-desktop-046.ps1',
  'deploy/cloud/scripts/desktop_046_guard.py', 'deploy/cloud/scripts/desktop_046_deploy.py',
  'deploy/cloud/scripts/android_124_publication.py',
  'scripts/tests/test_desktop_046_guard.py', 'scripts/tests/test_android_124_publication.py',
  'scripts/lib/reviewed-source.cjs', 'scripts/lib/reviewed-source.node-test.cjs',
  'scripts/build-desktop-045.ps1', 'scripts/sign-desktop-045.ps1',
  'scripts/desktop-045-deploy-entry.ps1', 'scripts/desktop-045-publish-entry.ps1',
  'scripts/lib/desktop-045.cjs', 'scripts/lib/desktop-045.node-test.cjs',
  'deploy/cloud/scripts/desktop_045_guard.py', 'scripts/tests/test_desktop_045_guard.py',
  'deploy/cloud/scripts/desktop_045_deploy.py', 'scripts/invoke-desktop-045.ps1',
  'scripts/stock_import.py',
  'scripts/tests/test_stock_resources.py',
  'scripts/invoke-stock-upgrade.ps1',
  'deploy/cloud/scripts/stock_deploy.py',
  'deploy/cloud/scripts/stock_guard.py',
  'docs/releases/2026-10-05-stock-cloud-handoff.md',
  'docs/releases/2026-10-05-stock-verification.md',
  'docs/inventory/2026-10-05-photo-stock-review.csv',
  'docs/inventory/2026-10-05-photo-stock-notes.md',
  'docs/inventory/2026-10-05-photo-stock-import.md',
  'docs/releases/2026-10-05-stock-release.md',
  ...['build-stock-source.ps1','build-stock-release.ps1','sign-stock-release.ps1',
    'publish-stock-release.ps1'].map(file => `scripts/${file}`),
  ...['stock-source.cjs','stock-release.cjs','stock-release.node-test.cjs',
    'stock-mobile.ps1'].map(file => `scripts/lib/${file}`),
  'scripts/tests/test-stock-source.ps1',
  '.gitignore', '.editorconfig', '.env.example', 'README.md', 'docker-compose.yml',
  'server/run.py', 'server/requirements.txt', 'server/requirements-dev.txt',
  'server/Dockerfile', 'server/.dockerignore', 'server/docker-entrypoint.sh', 'server/pytest.ini',
  'client/build/windows-target.nsh',
  'server/pyproject.toml', 'server/.env.example', 'server/migrations/alembic.ini',
  'server/migrations/script.py.mako',
  ...['client', 'mobile'].flatMap(area => ['package.json', 'package-lock.json',
    'index.html', 'vite.config.ts', 'vitest.config.ts', 'tsconfig.json',
    'tsconfig.app.json', 'tsconfig.node.json', '.env.example'].map(file => `${area}/${file}`)),
  'mobile/capacitor.config.ts', 'mobile/version.json',
  'mobile/android/.gitignore', 'mobile/android/app/.gitignore',
  'mobile/android/app/src/main/AndroidManifest.xml',
  ...['build.gradle', 'settings.gradle', 'variables.gradle', 'gradle.properties',
    'gradlew', 'gradlew.bat', 'capacitor.settings.gradle',
    'app/build.gradle', 'app/capacitor.build.gradle', 'app/proguard-rules.pro',
    'gradle/wrapper/gradle-wrapper.properties', 'gradle/wrapper/gradle-wrapper.jar']
    .map(file => `mobile/android/${file}`),
  'deploy/cloud/docker-compose.prod.yml', 'deploy/cloud/.env.example',
  'deploy/cloud/nginx/http.conf.template', 'deploy/cloud/nginx/https.conf.template',
  ...['backup.sh', 'backup-role.sql', 'bootstrap-ubuntu.sh', 'common.sh',
    'first-deploy.sh', 'install-cron.sh', 'prepare-env.sh', 'renew-certificates.sh',
    'reset-role.sql', 'restore.sh', 'runtime-role.sql', 'update.sh',
    'operations_backup_verify.py', 'operations_cleanup.py', 'operations_preflight.py',
    'operations_deploy.py', 'operations_offline_build.py', 'operations_resume.py',
    'operations_preview_recovery.py'].map(file => `deploy/cloud/scripts/${file}`),
  ...['build-cloud-bundle.ps1', 'build-mobile-release.ps1', 'build-mobile-web.ps1',
    'build-owner-reset-source.ps1', 'build-security-upgrade.ps1', 'build-web-release.ps1',
    'build-windows-delivery.ps1', 'build-windows-release.ps1', 'deploy-security-upgrade.sh',
    'new-desktop-release-key.ps1', 'publish-electron-update.ps1', 'publish-mobile-release.ps1',
    'publish-web-release.ps1', 'publish-windows-release.ps1', 'sign-windows-release.ps1',
    'start-dev-client.ps1', 'start-dev-server.ps1', 'test-all.ps1', 'test-windows-compat.ps1',
    'upload-security-upgrade.ps1', 'prepare-source-baseline.ps1',
    'build-operations-release.ps1', 'build-operations-source.ps1', 'build-operations-deploy.ps1',
    'deploy-operations-upgrade.sh', 'upload-operations-upgrade.ps1',
    'invoke-operations-cutover.ps1', 'invoke-operations-offline-build.ps1',
    'invoke-operations-resume.ps1'].map(file => `scripts/${file}`),
  ...['cloud-archive.ps1', 'desktop-release-fixture.cjs', 'desktop-release.cjs',
    'desktop-release.node-test.cjs', 'desktop-signing.cjs', 'desktop-signing.node-test.cjs',
    'mobile-release-signature.ps1', 'release-policy.ps1', 'security-release-bundle.ps1',
    'windows-delivery.cjs', 'windows-delivery.node-test.cjs', 'windows-public-check.cjs',
    'windows-public-check.node-test.cjs', 'windows-publish.cjs', 'windows-publish.node-test.cjs',
    'source-security.cjs', 'source-security.node-test.cjs',
    'operations-release.cjs', 'operations-release.node-test.cjs'].map(file => `scripts/lib/${file}`),
  ...['mobile-asset-policy.ps1', 'test-cloud-archive.ps1', 'test-electron-publish-manifest.ps1',
    'test-mobile-apk-assets.ps1', 'test-mobile-asset-policy.ps1', 'test-mobile-release-signature.ps1',
    'test-owner-reset-cloud-config.ps1', 'test-owner-reset-source.ps1', 'test-release-policy.ps1',
    'test-security-release-bundle.ps1', 'test-windows-build.ps1', 'test-windows-delivery.ps1',
    'test-windows-publish.ps1', 'test-windows-tools.ps1', 'windows-release-fixture.cjs',
    'test-operations-source.ps1', 'test-operations-upload.ps1',
    'test-operations-cutover.ps1', 'test-operations-resume.ps1'].map(file => `scripts/tests/${file}`),
])
const SOURCE_EXT = new Set(['.py', '.ts', '.vue', '.cjs', '.js', '.json', '.md',
  '.sql', '.sh', '.ps1', '.html', '.css', '.svg', '.java', '.xml', '.png', '.webmanifest'])
const BINARY_EXT = new Set(['.png', '.jar'])

function normalized(relative) {
  if (typeof relative !== 'string' || path.win32.isAbsolute(relative) || path.posix.isAbsolute(relative))
    throw new Error('Forbidden source path')
  const value = relative.replace(/\\/g, '/')
  if (!value || value.split('/').some(part => !part || part === '.' || part === '..' || part.includes(':')))
    throw new Error('Forbidden source path')
  return value
}
function allowed(relative) {
  if (FILES.has(relative)) return true
  if (relative === 'mobile/android/app/src/main/res/xml/config.xml') return false
  // Prior operational notes remain untouched; only reviewed current plans
  // enter this baseline. They may contain old command examples/credentials.
  const datedDoc = /^docs\/superpowers\/(?:plans|specs)\/(\d{4}-\d{2}-\d{2})-/.exec(relative)
  if (datedDoc && datedDoc[1] < '2026-10-04') return false
  if (!SOURCE_EXT.has(path.posix.extname(relative))) return false
  const parts = relative.split('/')
  if (parts.some((part, index) => ['node_modules', '__pycache__', 'dist', 'private', '.gradle'].includes(part)
      || (part === 'build' && !(index === 1 && parts[0] === 'client')))) return false
  return TREES.some(tree => relative.startsWith(`${tree}/`))
}
function safeFile(root, relative) {
  relative = normalized(relative)
  if (!allowed(relative)) throw new Error(`Forbidden source path: ${relative}`)
  const base = fs.realpathSync(root)
  let current = base
  for (const part of relative.split('/')) {
    current = path.join(current, part)
    if (fs.lstatSync(current).isSymbolicLink()) throw new Error(`Forbidden source path: ${relative}`)
  }
  if (!fs.statSync(current).isFile()) throw new Error(`Forbidden source path: ${relative}`)
  return current
}
function enumerateSourceFiles(root) {
  const base = fs.realpathSync(root)
  const found = new Set()
  function visit(relative) {
    const file = path.join(base, relative)
    if (!fs.existsSync(file)) return
    const stat = fs.lstatSync(file)
    if (stat.isSymbolicLink()) return
    if (stat.isDirectory()) {
      for (const name of fs.readdirSync(file).sort()) {
        if (['node_modules','__pycache__','build','dist','private','.gradle'].includes(name)) continue
        visit(`${relative}/${name}`)
      }
    } else if (stat.isFile() && allowed(relative)) {
      safeFile(base, relative)
      found.add(relative)
    }
  }
  for (const tree of TREES) visit(tree)
  for (const file of FILES) {
    if (fs.existsSync(path.join(base, file))) {
      try { safeFile(base, file); found.add(file) }
      catch { throw new Error(`Forbidden source path: ${file}`) }
    }
  }
  return [...found].sort()
}
function findingsFor(relative, content) {
  const results = []
  const testFile = /^server\/tests\//.test(relative) ||
    /(?:\.test\.ts|\.node-test\.cjs|scripts\/tests\/|\.fixture\.cjs|desktop-release-fixture\.cjs)$/.test(relative)
  const doc = relative.startsWith('docs/')
  const template = relative.endsWith('.env.example')
  const lines = content.split(/\r?\n/)
  function report(index, rule) { results.push({path:relative, line:index+1, rule}) }
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const dsn = /(?:postgres(?:ql)?(?:\+\w+)?|mysql|https?):\/\/[^\s/:]+:([^\s@]+)@/i.exec(line)
    if (dsn) {
      const placeholder = /^(?:\$\{|<|change[-_]|replace[-_]|your[-_])/i.test(dsn[1])
      if (!testFile && !placeholder) report(i, 'credential-dsn')
    }
    if (/-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----/.test(line) &&
        lines.slice(i+1, i+10).some(value => /^[A-Za-z0-9+/]{40,}={0,2}$/.test(value.trim()))) report(i, 'private-key-material')
    if (/\bLTAI[A-Za-z0-9]{12,}\b/.test(line) && !testFile) report(i, 'cloud-access-key')
    const literal = /\b(?:password|passwd|secret|token|api_key|access_key_secret|jwt_secret_key|secret_key|audit_hmac_key)\b["']?\s*(?:=|:)\s*["']([^"'\r\n]+)["']/ig
    for (const match of line.matchAll(literal)) {
      const value = match[1]
      if (testFile || /^(?:\$\{|\$\(|<|dev-only-)/.test(value)) continue
      if (doc && /^(?:fixture-|admin123$|test-only-)/.test(value)) continue
      if (value.length >= 8 && !/^(?:password|secret|token|https?:\/\/|\*+)$/.test(value)) report(i, 'literal-credential')
    }
    if (template) {
      const match = /^\s*(?:POSTGRES_PASSWORD|SECRET_KEY|JWT_SECRET_KEY|AUDIT_HMAC_KEY|ALIBABA_CLOUD_ACCESS_KEY_SECRET)=(.+)$/i.exec(line)
      if (match && !/^(?:\s*$|change|replace|your-|\$\{|<)/i.test(match[1])) report(i, 'template-credential')
    }
  }
  return results.filter((row, i) => !results.slice(0, i).some(prev => prev.line === row.line && prev.rule === row.rule))
}
function scanSourceFiles(root, files, options = {}) {
  const findings = []
  for (const input of files) {
    const relative = normalized(input)
    const file = safeFile(root, relative)
    if (BINARY_EXT.has(path.extname(file))) continue
    let content
    if (options.index) {
      const result = spawnSync('git', ['show', `:${relative}`], {cwd:root, encoding:'utf8', maxBuffer:32*1024*1024, windowsHide:true})
      if (result.status !== 0) throw new Error(`Cannot inspect staged source: ${relative}`)
      content = result.stdout
    } else content = fs.readFileSync(file, 'utf8')
    findings.push(...findingsFor(relative, content))
  }
  return findings
}
function assertSourceSafe(root, files, options) {
  const findings = scanSourceFiles(root, files, options)
  if (findings.length) throw new Error(findings.map(row => `${row.path}:${row.line} [${row.rule}]`).join('\n'))
}
module.exports = {enumerateSourceFiles, scanSourceFiles, assertSourceSafe, allowed}
if (require.main === module) {
  try {
    const root = path.resolve(__dirname, '../..')
    const index = process.argv.includes('--index')
    let files = enumerateSourceFiles(root)
    if (index) {
      const result = spawnSync('git', ['diff','--cached','--name-only','--diff-filter=ACMR','-z'], {cwd:root, encoding:'utf8',windowsHide:true})
      if (result.status !== 0) throw new Error('Cannot inspect Git index')
      files = result.stdout.split('\0').filter(Boolean)
    }
    assertSourceSafe(root, files, {index})
    if (process.argv.includes('--list')) process.stdout.write(JSON.stringify(files))
    else process.stdout.write(`SOURCE_SAFE: ${files.length} files\n`)
  } catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1 }
}
