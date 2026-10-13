const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto')
const release=require('../lib/desktop-056.cjs'),{fixture}=require('../lib/desktop-release-fixture.cjs'),{makeReleasePayload}=require('../lib/desktop-release.cjs'),{getTarget}=require('../../client/electron/target-profiles.cjs')
function envelope(f,target,sequence){
 const name=`Xiquan-Bathhouse-Setup-0.5.5-${target}.exe`
 const payload=makeReleasePayload({profile:getTarget(target),version:'0.5.5',buildId:'previous',releaseTrust:f.trust,artifact:{fileName:name,size:5,sha256:'a'.repeat(64),sha512:Buffer.alloc(64,1).toString('base64')},blockmap:{fileName:name+'.blockmap',size:2,sha256:'b'.repeat(64)},updaterManifest:{fileName:'latest.yml',sha256:'c'.repeat(64)}},{sequence,minimumVersion:'0.4.2'})
 const bytes=Buffer.from(JSON.stringify(payload));return {payload:bytes.toString('base64'),signature:crypto.sign(null,bytes,f.privateKey).toString('base64')}
}
test('0.5.6 signs above online and retained histories, preserving the original per-target trust',async t=>{
 const f=await fixture(false);t.after(f.close)
 const plan=await release.signingPlan({trust:f.trust,readPolicy:async target=>envelope(f,target,15),history:[{target:'win10-x64',envelope:envelope(f,'win10-x64',17)}]})
 assert.equal(plan.version,'0.5.6');assert.equal(plan.sequence,18);assert.equal(release.validatePlan(plan,{trust:f.trust}),true)
 assert.throws(()=>release.validatePlan({...plan,sequence:1},{trust:f.trust}))
})
test('0.5.6 publication requires exact API, web and completed public checks, never just an old deployment',t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'xiquan056-receipt-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}))
 fs.mkdirSync(path.join(dir,'private/desktop056'),{recursive:true})
 const info={ProjectRoot:dir,SourceCommit:'a'.repeat(40),ApiSha256:'b'.repeat(64),WebSha256:'c'.repeat(64)}
 const receipt={version:'0.5.6',source_commit:info.SourceCommit,api_sha256:info.ApiSha256,web_sha256:info.WebSha256,image_id:'sha256:'+'d'.repeat(64),database_changed:false,public_verified:false}
 const file=path.join(dir,'private/desktop056/completed.json'),source=require('../lib/desktop-056-source.cjs')
 fs.writeFileSync(file,JSON.stringify(receipt));assert.throws(()=>source.assertCloudCompletion(info))
 fs.writeFileSync(file,JSON.stringify({...receipt,public_verified:true}));assert.equal(source.assertCloudCompletion(info).databaseChanged,false)
 fs.writeFileSync(file,JSON.stringify({...receipt,public_verified:true,api_sha256:'e'.repeat(64)}));assert.throws(()=>source.assertCloudCompletion(info))
})
