const test=require('node:test'),assert=require('node:assert/strict')
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto')
const {spawnSync}=require('node:child_process')
const {eligibleCleanup,permittedCandidate,scanZip,assertPreparedChanges}=require('./archive-proof.cjs')
const root='F:\\溪泉洗浴系统',now=new Date('2026-10-11T04:00:00Z')
const entry={version:'0.4.9',sourceCommit:'a'.repeat(40),absolutePath:root+'\\release\\windows\\0.4.9\\old-build\\win11-x64\\Xiquan-Bathhouse-Setup-0.4.9-win11-x64.exe',size:100,sha256:'a'.repeat(64),remoteSha256:'a'.repeat(64),remoteUrl:'https://github.com/Rasmus911/xiquanxiyu/blob/'+ 'b'.repeat(40)+'/archive/desktop/0.4.9/installers/parts-manifest.json',verifiedAt:now.toISOString()}
const proof={repository:'https://github.com/Rasmus911/xiquanxiyu',entries:[entry]}
test('individual historical artifact needs exact fresh matching remote proof',()=>{
  assert.deepEqual(eligibleCleanup(entry,proof,{root,now}),entry)
  assert.throws(()=>eligibleCleanup(entry,{...proof,entries:[]},{root,now}))
  assert.throws(()=>eligibleCleanup({...entry,sha256:'c'.repeat(64)},proof,{root,now}))
  assert.throws(()=>eligibleCleanup(entry,proof,{root,now:new Date('2026-10-13T04:00:00Z')}))
})
test('root, current releases, secrets, path escapes and wrong repository are never cleanup candidates',()=>{
  for(const absolutePath of [root,root+'\\private\\key.pem',root+'\\server\\app\\models.py',root+'\\release\\windows\\0.5.0\\old.exe',root+'\\release\\mobile\\xiquan-mobile-ordering-1.2.9.apk','F:\\other\\old.exe',root+'\\release\\cloud\\..\\..\\private\\secret.zip']){
    assert.throws(()=>eligibleCleanup({...entry,absolutePath},proof,{root,now}))
    assert.equal(permittedCandidate(absolutePath,root),false)
  }
  assert.throws(()=>eligibleCleanup({...entry,remoteUrl:'https://github.com/else/project/blob/'+ 'b'.repeat(40)+'/old.exe'},proof,{root,now}))
  assert.throws(()=>eligibleCleanup({...entry,remoteSha256:'c'.repeat(64)},proof,{root,now}))
  assert.throws(()=>eligibleCleanup(entry,{...proof,repository:'https://github.com/else/project'},{root,now}))
})
test('known old delivery documents and Android 1.2.8 may be classified without matching latest artifacts',()=>{
  assert.equal(permittedCandidate(root+'\\最新版安装包-账号注册-0.4.9\\01-部署云端.ps1',root),true)
  assert.equal(permittedCandidate(root+'\\最新版安装包-注册令牌-手机版1.2.8\\操作说明.md',root),true)
  assert.equal(permittedCandidate(root+'\\release\\mobile\\xiquan-mobile-ordering-1.2.8.apk',root),true)
  assert.equal(permittedCandidate(root+'\\release\\cloud\\unknown.zip',root),false)
})
test('historical compressed text is fully reviewed with exact uncompressed byte counts',async t=>{
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'xiquan-archive-review-'))
  t.after(()=>fs.rmSync(folder,{recursive:true,force:true}))
  const zip=path.join(folder,'review.zip')
  const content=JSON.stringify({files:Array.from({length:4000},(_,i)=>({file:'server/app/file'+i+'.py',size:i,sha256:'a'.repeat(64)}))})
  fs.writeFileSync(path.join(folder,'source-manifest.json'),content)
  const command="Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::CreateFromDirectory($env:XIQUAN_ARCHIVE_TEST_FOLDER,$env:XIQUAN_ARCHIVE_TEST_ZIP)"
  const zipFolder=path.join(folder,'contents');fs.mkdirSync(zipFolder);fs.renameSync(path.join(folder,'source-manifest.json'),path.join(zipFolder,'source-manifest.json'))
  const r=spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',command],{env:{...process.env,XIQUAN_ARCHIVE_TEST_FOLDER:zipFolder,XIQUAN_ARCHIVE_TEST_ZIP:zip},timeout:30000,encoding:'utf8',windowsHide:true})
  assert.equal(r.status,0,r.stderr)
  const result=await scanZip(zip)
  assert.equal(result.entries,1)
  assert.equal(result.bytes,Buffer.byteLength(content))
})
test('interrupted owned archive preparation can resume but never overwrites unrelated changes',async t=>{
  const clone=fs.mkdtempSync(path.join(os.tmpdir(),'xiquan-archive-owned-'))
  t.after(()=>fs.rmSync(clone,{recursive:true,force:true}))
  const file='archive/desktop/0.4.9/delivery-20261011/notes.md',data='Reviewed release notes\n'
  fs.mkdirSync(path.dirname(path.join(clone,file)),{recursive:true});fs.writeFileSync(path.join(clone,file),data)
  const expected=new Map([[file,crypto.createHash('sha256').update(data).digest('hex')]])
  await assertPreparedChanges(clone,'?? archive/desktop/0.4.9/delivery-20261011/\0',expected)
  fs.writeFileSync(path.join(clone,file),'User edit')
  await assert.rejects(assertPreparedChanges(clone,'?? archive/desktop/0.4.9/delivery-20261011/\0',expected))
  await assert.rejects(assertPreparedChanges(clone,' M README.md\0',expected))
})
