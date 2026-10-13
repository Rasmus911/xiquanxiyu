const test=require('node:test'),assert=require('node:assert/strict'),crypto=require('node:crypto'),fs=require('node:fs'),path=require('node:path')
const {fixture}=require('../lib/desktop-release-fixture.cjs')
const {makeReleasePayload}=require('../lib/desktop-release.cjs')
const {getTarget}=require('../../client/electron/target-profiles.cjs')
const file=path.join(__dirname,'../lib/desktop-055.cjs')
const release=fs.existsSync(file)?require(file):{}
const targets=['win10-x86','win10-x64','win11-x86','win11-x64']
function signed(f,target,sequence,version='0.5.2'){
  const name=`Xiquan-Bathhouse-Setup-${version}-${target}.exe`,hash='a'.repeat(64)
  const payload=makeReleasePayload({profile:getTarget(target),version,buildId:'historical',releaseTrust:f.trust,
    artifact:{fileName:name,size:120,sha256:hash,sha512:Buffer.alloc(64,1).toString('base64')},
    blockmap:{fileName:name+'.blockmap',size:50,sha256:hash},updaterManifest:{fileName:'latest.yml',sha256:hash}},
    {sequence,minimumVersion:'0.4.2'})
  const bytes=Buffer.from(JSON.stringify(payload))
  return {payload:bytes.toString('base64'),signature:crypto.sign(null,bytes,f.privateKey).toString('base64')}
}
test('new publication exceeds retained signed history even when online policies rolled back',async t=>{
  assert.equal(typeof release.signingPlan,'function')
  const f=await fixture(false);t.after(f.close)
  const history=[{target:'win10-x86',envelope:signed(f,'win10-x86',51)}]
  const plan=await release.signingPlan({trust:f.trust,readPolicy:async target=>signed(f,target,9),history})
  assert.equal(plan.version,'0.5.5');assert.equal(plan.sequence,52)
  assert.equal(plan.history[0].sequence,51)
  assert.deepEqual(release.releaseNotes,['取消下单“选择耗材”的步骤','可以通过导入外部Excel来整理库存'])
})
test('unsigned, modified or wrong-target history cannot set a sequence floor',async t=>{
  const f=await fixture(false);t.after(f.close)
  const record={target:'win10-x86',envelope:signed(f,'win10-x86',51)}
  await assert.rejects(release.signingPlan({trust:f.trust,readPolicy:async target=>signed(f,target,9),history:[{...record,target:'win11-x64'}]}))
  record.envelope.signature=Buffer.alloc(64).toString('base64')
  await assert.rejects(release.signingPlan({trust:f.trust,readPolicy:async target=>signed(f,target,9),history:[record]}))
})
test('a caller cannot supply a guessed sequence in a plan for partial signing',async t=>{
  assert.equal(typeof release.validatePlan,'function')
  const f=await fixture(false);t.after(f.close)
  const plan=await release.signingPlan({trust:f.trust,readPolicy:async target=>signed(f,target,9),history:[]})
  assert.equal(plan.sequence,10)
  assert.equal(release.validatePlan(plan,{trust:f.trust}),true)
  assert.throws(()=>release.validatePlan({...plan,sequence:10000},{trust:f.trust}),/sequence/i)
})
test('publication refuses a completed baseline unless the required exact server correction is proven',t=>{
  const root=fs.mkdtempSync(path.join(require('node:os').tmpdir(),'xiquan055-correction-test-'))
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}))
  fs.mkdirSync(path.join(root,'private/desktop055'),{recursive:true})
  const correction={kind:'pending-readonly-select',file:'server/app/api/inventory_excel.py',original_sha256:'c'.repeat(64),corrected_sha256:'d'.repeat(64)}
  const info={ProjectRoot:root,SourceCommit:'a'.repeat(40),SourceSha256:'b'.repeat(64),ServerCorrection:correction}
  const receipt={phase:'completed',target_schema:'20261013_manual_inventory_excel',source_commit:info.SourceCommit,
    source_sha256:info.SourceSha256,image_id:'sha256:'+'e'.repeat(64),origin:{hashes:{'/app/index.html':'f'.repeat(64)}}}
  const file=path.join(root,'private/desktop055/completed.json'),source=require('../lib/desktop-055-source.cjs')
  fs.writeFileSync(file,JSON.stringify(receipt))
  assert.throws(()=>source.assertCloudCompletion(info),/correction/i)
  fs.writeFileSync(file,JSON.stringify({...receipt,server_correction:correction}))
  assert.equal(source.assertCloudCompletion(info).verified,true)
  fs.writeFileSync(file,JSON.stringify({...receipt,server_correction:{...correction,corrected_sha256:'0'.repeat(64)}}))
  assert.throws(()=>source.assertCloudCompletion(info),/correction/i)
})
