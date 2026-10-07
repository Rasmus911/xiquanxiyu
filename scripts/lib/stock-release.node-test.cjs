const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { createRequire } = require('node:module')
const fromClient = createRequire(path.resolve(__dirname, '../../client/package.json'))
const asar = fromClient('@electron/asar'), yaml = fromClient('js-yaml')
const { fixture } = require('./desktop-release-fixture.cjs')
const { trust } = require('./operations-release.cjs')
const modulePath = path.join(__dirname, 'stock-release.cjs')
test('stock candidate verifies six actual payloads and rejects missing target, wrong trust, version, runtime and production pending', async () => {
  assert.ok(fs.existsSync(modulePath), 'stock release validator must exist')
  const { collectWindows, validateIdentity, validateAndroid } = require(modulePath)
  const f = await fixture(false)
  try {
    for (const id of ['win7-x86','win7-x64','win10-x86','win10-x64','win11-x86','win11-x64']) {
      const source = path.join(f.root, 'fixture-source-' + id)
      const metadata = JSON.parse(fs.readFileSync(path.join(source, 'package.json')))
      metadata.version = '0.4.4'; metadata.xiquanDesktop.releaseTrust = trust
      fs.writeFileSync(path.join(source, 'package.json'), JSON.stringify(metadata))
      await asar.createPackage(source, path.join(f.root, id, id.endsWith('x86') ? 'win-ia32-unpacked' : 'win-unpacked', 'resources/app.asar'))
      for (const suffix of ['', '.blockmap']) fs.renameSync(path.join(f.root,id,`Xiquan-Bathhouse-Setup-0.4.2-${id}.exe${suffix}`),path.join(f.root,id,`Xiquan-Bathhouse-Setup-0.4.4-${id}.exe${suffix}`))
      const manifestPath = path.join(f.root,id,'latest.yml')
      fs.writeFileSync(manifestPath, fs.readFileSync(manifestPath,'utf8').replaceAll('0.4.2','0.4.4'))
    }
    const rows = await collectWindows(f.root)
    assert.deepEqual(rows.map(row => [row.target,row.arch,row.runtime]), [
      ['win7-x86','ia32','22.3.27'],['win7-x64','x64','22.3.27'],
      ['win10-x86','ia32','43.7.7'],['win10-x64','x64','44.5.1'],
      ['win11-x86','ia32','43.7.7'],['win11-x64','x64','44.5.1']])
    const manifest = {schema:1,mode:'candidate',source_commit:'a'.repeat(40),build_id:'fixture-build',trust_key_id:trust.keyId,
      desktop_version:'0.4.4',android_version:'1.2.3',android_version_code:10,targets:rows,android:null}
    validateIdentity(manifest)
    assert.throws(() => validateIdentity({...manifest,targets:rows.slice(1)}), /six|targets/)
    assert.throws(() => validateIdentity({...manifest,trust_key_id:'wrong'}), /trust/)
    assert.throws(() => validateIdentity({...manifest,desktop_version:'0.4.3'}), /version/)
    assert.throws(() => validateIdentity({...manifest,targets:rows.map((r,i)=>i? r : {...r,runtime:'44.5.1'})}), /runtime/)
    assert.throws(() => validateIdentity({...manifest,source_commit:'not-commit'}), /commit/)
    assert.throws(() => validateIdentity(manifest, true), /pending|candidate/)
    assert.throws(() => validateAndroid({certificate_sha256:'1'.repeat(64),version:'1.2.3',version_code:10,package:'com.xiquan.mobileordering'}), /original/)
    const exe = path.join(f.root,'win7-x86','win-ia32-unpacked','溪泉洗浴管理系统.exe')
    fs.writeFileSync(exe, require('./desktop-release-fixture.cjs').pe('x64'))
    await assert.rejects(() => collectWindows(f.root), /架构/)
  } finally { f.close() }
})
test('unknown, incomplete and forged previous policies cannot authorize signing', async () => {
  assert.ok(fs.existsSync(modulePath), 'stock release validator must exist')
  const { signingPlan } = require(modulePath)
  await assert.rejects(() => signingPlan(async () => { throw Error('timeout') }), /timeout/)
  await assert.rejects(() => signingPlan(async () => ({status:404})), /签名|policy|payload|封装/)
  await assert.rejects(() => signingPlan(async () => ({payload:'e30=',signature:'fake'})), /签名|policy|payload|封装/)
})
