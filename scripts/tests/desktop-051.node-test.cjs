const test=require('node:test'),assert=require('node:assert/strict'),crypto=require('node:crypto')
const fs=require('node:fs'),os=require('node:os'),path=require('node:path')
const release=require('../lib/desktop-051.cjs')
const {makeReleasePayload}=require('../lib/desktop-release.cjs')
const {getTarget}=require('../../client/electron/target-profiles.cjs')
function policies(){
  const {privateKey,publicKey}=crypto.generateKeyPairSync('ed25519')
  const trust={testOnly:false,publicKeyPem:publicKey.export({type:'spki',format:'pem'}),keyId:crypto.createHash('sha256').update(publicKey.export({type:'spki',format:'der'})).digest('hex').slice(0,16)}
  const rows=new Map()
  release.targets.forEach((id,i)=>{
    const fileName=`Xiquan-Bathhouse-Setup-0.5.0-${id}.exe`,sha256='a'.repeat(64)
    const payload=makeReleasePayload({profile:getTarget(id),version:'0.5.0',buildId:'fixture',releaseTrust:trust,
      artifact:{fileName,size:120,sha256,sha512:Buffer.alloc(64,1).toString('base64')},blockmap:{fileName:fileName+'.blockmap',size:50,sha256},updaterManifest:{fileName:'latest.yml',sha256}},
    {sequence:31+i,minimumVersion:i===0?'0.4.3':'0.4.2',required:false,releaseNotes:[]})
    const bytes=Buffer.from(JSON.stringify(payload));rows.set(id,{payload:bytes.toString('base64'),signature:crypto.sign(null,bytes,privateKey).toString('base64')})
  });return {trust,rows}
}
test('four real signed previous policies retain per-target floors and advance maximum',async()=>{
  const p=policies(),read=[]
  const result=await release.signingPlan({trust:p.trust,readPolicy:async id=>{read.push(id);return p.rows.get(id)}})
  assert.deepEqual(read,release.targets);assert.equal(result.version,'0.5.1');assert.equal(result.sequence,35)
  assert.deepEqual(result.previous.map(r=>r.minimum_version),['0.4.3','0.4.2','0.4.2','0.4.2'])
  assert.deepEqual(release.releaseNotes,['增加实体卡消费功能'])
  assert.equal(release.trust.keyId,'b26477a9ed540ad0')
})
test('offline, forged and mismatched policies stop without bootstrap sequence',async()=>{
  const p=policies()
  await assert.rejects(release.signingPlan({trust:p.trust,readPolicy:async()=>{throw Error('offline')}}),/offline/)
  await assert.rejects(release.signingPlan({trust:p.trust,readPolicy:async()=>p.rows.get('win11-x64')}))
  await assert.rejects(release.signingPlan({trust:p.trust,readPolicy:async id=>({...p.rows.get(id),signature:Buffer.alloc(64).toString('base64')})}))
})
test('completed evidence binds current source, schema, image, running worker and released maintenance',()=>{
  const delivery={SourceCommit:'a'.repeat(40),SourceSha256:'b'.repeat(64)}
  const receipt={phase:'completed',target_schema:'20261012_physical_membership',source_commit:delivery.SourceCommit,source_sha256:delivery.SourceSha256,image_id:'sha256:'+'c'.repeat(64),origin:{hashes:{'web/index.html':'d'.repeat(64)}}}
  const state={image_id:receipt.image_id,api_healthy:true,worker_healthy:true,maintenance:false}
  assert.equal(release.validateCompletion(receipt,delivery,state).source_commit,delivery.SourceCommit)
  for(const patch of [{target_schema:'20261011_service_receipts'},{source_commit:'e'.repeat(40)},{phase:'ready'},{origin:{}}])assert.throws(()=>release.validateCompletion({...receipt,...patch},delivery,state))
  for(const patch of [{api_healthy:false},{worker_healthy:false},{maintenance:true},{image_id:'sha256:'+'e'.repeat(64)}])assert.throws(()=>release.validateCompletion(receipt,delivery,{...state,...patch}))
})
test('delivered leaf bytes are checked before connection; traversal and tamper rejected',async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'xiquan051-delivery-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}))
  const file='source.zip';fs.writeFileSync(path.join(root,file),'fixture')
  const records=[{file,size:7,sha256:crypto.createHash('sha256').update('fixture').digest('hex')}]
  await release.verifyDeliveryFiles(root,records)
  await assert.rejects(release.verifyDeliveryFiles(root,[{...records[0],file:'../source.zip'}]))
  fs.writeFileSync(path.join(root,file),'changed');await assert.rejects(release.verifyDeliveryFiles(root,records),/hash/)
})
