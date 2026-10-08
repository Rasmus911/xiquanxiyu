const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

// The break these tests catch: admitting private/generated paths or revealing
// a literal credential when establishing the source-control baseline.
function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'xiquan-source-test-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  return root
}
function write(root, relative, content = 'safe\n') {
  const file = path.join(root, relative)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, content)
}
function api() { return require('./source-security.cjs') }

test('source inventory excludes private config build output and ad hoc SSH scripts', t => {
  const root = fixture(t)
  for (const name of ['server/app/main.py', 'server/migrations/alembic.ini',
    'server/migrations/script.py.mako', 'server/.dockerignore', 'client/build/windows-target.nsh',
    'client/build/windows-pack.cjs', 'client/src/main.ts', 'mobile/src/main.ts',
    'mobile/android/app/src/main/java/com/xiquan/MainActivity.java',
    'scripts/build-windows-release.ps1', 'deploy/cloud/docker-compose.prod.yml',
    '.env.example', 'docs/superpowers/plans/safe.md']) write(root, name)
  for (const name of ['private/key.pem', '.env.production', 'server/.env',
    'scripts/ssh_try_passwords.py', 'scripts/unknown-upload.py',
    'client/src/private.key', 'client/src/download.exe',
    'mobile/android/local.properties', 'mobile/android/app/build/test.json',
    'mobile/android/app/src/main/assets/public/index.html',
    'mobile/android/app/src/main/res/xml/config.xml',
    'deploy/cloud/nginx/active.conf', 'deploy/cloud/updates/latest.yml',
    'release/secret.json']) write(root, name)
  assert.deepEqual(api().enumerateSourceFiles(root), [
    '.env.example', 'client/build/windows-pack.cjs', 'client/build/windows-target.nsh',
    'client/src/main.ts', 'deploy/cloud/docker-compose.prod.yml',
    'docs/superpowers/plans/safe.md',
    'mobile/android/app/src/main/java/com/xiquan/MainActivity.java',
    'mobile/src/main.ts', 'scripts/build-windows-release.ps1', 'server/.dockerignore', 'server/app/main.py',
    'server/migrations/alembic.ini', 'server/migrations/script.py.mako',
  ])
})

test('credential findings give only locations and never sensitive values', t => {
  const root = fixture(t)
  const fake = 'test-only-never-a-real-secret-984321'
  write(root, 'server/app/bad.py', `PASSWORD = '${fake}'\n`)
  const findings = api().scanSourceFiles(root, ['server/app/bad.py'])
  assert.deepEqual(findings, [{ path: 'server/app/bad.py', line: 1, rule: 'literal-credential' }])
  assert.equal(JSON.stringify(findings).includes(fake), false)
  assert.throws(() => api().assertSourceSafe(root, ['server/app/bad.py']), /server\/app\/bad.py:1/)
})

test('paths outside allowlist are rejected before content is read', t => {
  const root = fixture(t)
  write(root, 'private/key.pem', 'do not read this')
  for (const relative of ['private/key.pem', '../outside.py', path.join(root, 'private/key.pem')]) {
    assert.throws(() => api().scanSourceFiles(root, [relative]), /source path/i)
  }
})

test('a symlink directory cannot import arbitrary files into the source list', t => {
  const root = fixture(t)
  write(root, 'private/hidden.py', 'do not read this')
  fs.mkdirSync(path.join(root, 'server/app'), { recursive: true })
  fs.symlinkSync(path.join(root, 'private'), path.join(root, 'server/app/linked'), 'junction')
  assert.deepEqual(api().enumerateSourceFiles(root), [])
  assert.throws(() => api().scanSourceFiles(root, ['server/app/linked/hidden.py']), /source path/i)
})

test('fictional test passwords do not grant a production-file exception', t => {
  const root = fixture(t)
  write(root, 'server/tests/test_auth.py', "password = 'fixture-only-password'\n")
  write(root, 'server/app/test_auth.py', "password = 'fixture-only-password'\n")
  assert.deepEqual(api().scanSourceFiles(root, ['server/tests/test_auth.py']), [])
  assert.equal(api().scanSourceFiles(root, ['server/app/test_auth.py']).length, 1)
})

test('private key material and password-bearing DSNs are blocked', t => {
  const root = fixture(t)
  write(root, 'server/app/unsafe.py', 'postgresql://user:fictional-secret@host/db\n' +
    '-----BEGIN PRIVATE KEY-----\n' + 'A'.repeat(64) + '\n-----END PRIVATE KEY-----\n')
  const findings = api().scanSourceFiles(root, ['server/app/unsafe.py'])
  assert.deepEqual(findings.map(row => row.rule), ['credential-dsn', 'private-key-material'])
})

test('placeholder DSNs and generated shell secrets are not real literal credentials', t => {
  const root = fixture(t)
  write(root, '.env.example', 'DATABASE_URL=postgresql://app:change-me@postgres/db\n')
  write(root, 'deploy/cloud/scripts/prepare-env.sh', 'SECRET_KEY="$(openssl rand -hex 32)"\n')
  assert.deepEqual(api().scanSourceFiles(root, ['.env.example', 'deploy/cloud/scripts/prepare-env.sh']), [])
  write(root, '.env.example', 'DATABASE_URL=postgresql://app:not-a-placeholder-abc@postgres/db\n')
  assert.equal(api().scanSourceFiles(root, ['.env.example']).length, 1)
})

test('older operational notes are preserved locally but not admitted into a new source baseline', t => {
  const root = fixture(t)
  write(root, 'docs/superpowers/plans/2026-09-19-mobile-ordering-android.md', 'historical-local-note')
  write(root, 'docs/superpowers/plans/2026-10-04-operations-upgrade.md', 'current-reviewed-plan')
  assert.deepEqual(api().enumerateSourceFiles(root), ['docs/superpowers/plans/2026-10-04-operations-upgrade.md'])
  assert.equal(fs.existsSync(path.join(root, 'docs/superpowers/plans/2026-09-19-mobile-ordering-android.md')), true)
})

test('048 reviewed deployment tools enter SOURCE while unreviewed neighboring scripts stay excluded', t => {
  const root = fixture(t)
  const reviewed = ['scripts/build-desktop-048.ps1', 'scripts/sign-desktop-048.ps1',
    'scripts/invoke-desktop-048.ps1', 'scripts/desktop-048-deploy-entry.ps1',
    'scripts/desktop-048-publish-entry.ps1', 'scripts/desktop-048-android-entry.ps1',
    'deploy/cloud/scripts/desktop_048_guard.py', 'deploy/cloud/scripts/desktop_048_deploy.py',
    'deploy/cloud/scripts/android_126_publication.py',
    'scripts/tests/test_desktop_048_guard.py', 'scripts/tests/test_desktop_048_memory.py',
    'scripts/tests/test_desktop_048_source.py', 'scripts/tests/test_desktop_048_entrypoints.py',
    'scripts/tests/test_android_126_publication.py']
  for (const name of reviewed) write(root, name)
  for (const name of ['deploy/cloud/scripts/desktop_050_deploy.py', 'scripts/invoke-desktop-050.ps1',
    'scripts/ssh_desktop048.py', 'private/desktop048.pem']) write(root, name)
  assert.deepEqual(api().enumerateSourceFiles(root), [...reviewed].sort())
})
