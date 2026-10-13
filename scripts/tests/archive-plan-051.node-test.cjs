const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto')
const archive=require('../lib/archive-plan-051.cjs')
const {spawnSync}=require('node:child_process')
test('private, latest APK and new delivery never qualify for archival deletion',()=>{
  for(const file of ['private/key.pem','release/mobile/xiquan-mobile-ordering-1.2.9.apk','最新版安装包-实体卡消费-0.5.1/setup.exe','server/migrations/a.py','release/runtime-cache/a.zip','release/windows/0.5.1/foo.exe','最新版安装包-账号与小票-0.5.0/.env','最新版安装包-账号与小票-0.5.0/signing-private.pem'])assert.equal(archive.allowed(file),false)
})
test('split manifest reconstructs exact bytes; substituted piece rejected',async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'xiquan051-archive-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}))
  const bytes=Buffer.from('0123456789abcdefghij'),source=path.join(root,'old.exe');fs.writeFileSync(source,bytes)
  const pieces=await archive.splitFile(source,root,'pieces/old.exe',7)
  assert.equal(pieces.length,3);assert.deepEqual(pieces.map(p=>p.size),[7,7,6])
  const entry={size:20,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),pieces}
  const read=file=>fs.readFileSync(path.join(root,file))
  await archive.verifyEntryBytes(entry,read)
  fs.writeFileSync(path.join(root,pieces[1].file),'bad');await assert.rejects(archive.verifyEntryBytes(entry,read),/piece/)
})
test('cleanup requires fresh exact repo, commit and local byte identity',()=>{
  const entry={path:'最新版安装包-账号与小票-0.5.0/setup.exe',size:3,sha256:'a'.repeat(64),pieces:[{file:'archive/desktop/0.5.0/x64/setup.exe',size:3,sha256:'a'.repeat(64)}]}
  const proof={repository:archive.repository,remoteCommit:'b'.repeat(40),verifiedAt:'2026-10-12T00:00:00Z',entries:[entry]}
  assert.equal(archive.validateProof(entry,proof,new Date('2026-10-12T01:00:00Z')),entry)
  for(const patch of [{repository:'https://github.com/other/repo'},{remoteCommit:'HEAD'},{verifiedAt:'2026-10-10T00:00:00Z'},{entries:[{...entry,sha256:'c'.repeat(64)}]}])assert.throws(()=>archive.validateProof(entry,{...proof,...patch},new Date('2026-10-12T01:00:00Z')))
})
test('archive upload batches are bounded even when all individually permitted blobs total several GiB',()=>{
  const sizes=[60,32,32,60,32].map((m,i)=>({file:'object'+i,size:m*1024*1024}))
  const batches=archive.partitionObjects(sizes,100*1024*1024)
  assert.equal(batches.length,3)
  assert.deepEqual(batches.flat(),sizes)
  assert.ok(batches.every(rows=>rows.reduce((n,row)=>n+row.size,0)<=100*1024*1024))
})
test('first archive batch accepts only its own binary-attributes addition to a tracked attributes file',async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'xiquan051-batch-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}))
  const clone=path.join(root,'clone');fs.mkdirSync(clone)
  const git=args=>{const r=spawnSync('git',['-C',clone,...args],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);return r.stdout}
  git(['init','-b','main']);git(['config','user.email','test@example.invalid']);git(['config','user.name','Archive test']);git(['config','core.autocrlf','false'])
  fs.writeFileSync(path.join(clone,'.gitattributes'),'*.zip -text\n');git(['add','.gitattributes']);git(['commit','-m','fixture']);git(['remote','add','origin',archive.repository])
  fs.writeFileSync(path.join(clone,'.gitattributes'),'*.zip -text\n\narchive/objects/** -text\n')
  const bytes=Buffer.from('original archive bytes'),sha256=crypto.createHash('sha256').update(bytes).digest('hex'),file='archive/objects/'+sha256
  fs.mkdirSync(path.join(clone,'archive/objects'),{recursive:true});fs.writeFileSync(path.join(clone,file),bytes)
  const input={entries:[{pieces:[{file,size:bytes.length,sha256}]}]},report=path.join(root,'batch.json')
  const result=await archive.stageBatch(input,clone,root,report)
  assert.equal(result.active,0);assert.equal(result.finished,false);assert.deepEqual(fs.readFileSync(path.join(clone,file)),bytes)
  assert.equal(git(['diff','--','.gitattributes']).includes('archive/objects/** -text'),true)
})
test('remote verification reassembles each unique object once but verifies every category and local leaf',async()=>{
  const bytes=Buffer.from('public bytes'),sha256=crypto.createHash('sha256').update(bytes).digest('hex'),file='archive/objects/'+sha256
  const first={path:'one',category:'documents/0.4.9',size:bytes.length,sha256,pieces:[{file,size:bytes.length,sha256}]},second={...first,path:'two',category:'desktop/0.4.9/shared'}
  const blobs=new Map([[file,bytes],['archive/'+first.category+'/desktop051-history.json',Buffer.from(JSON.stringify({repository:archive.repository,entries:[first]}))],['archive/'+second.category+'/desktop051-history.json',Buffer.from(JSON.stringify({repository:archive.repository,entries:[second]}))]])
  let pieceReads=0;const local=[]
  const entries=await archive.verifyRemoteEntries({entries:[first,second]},async name=>{if(name===file)pieceReads++;return blobs.get(name)},async entry=>local.push(entry.path))
  assert.equal(pieceReads,1);assert.deepEqual(local,['one','two']);assert.deepEqual(entries,[first,second])
  blobs.set('archive/'+second.category+'/desktop051-history.json',Buffer.from(JSON.stringify({repository:archive.repository,entries:[]})))
  await assert.rejects(archive.verifyRemoteEntries({entries:[first,second]},async name=>blobs.get(name),async()=>{}),/manifest differs/)
})
test('archive batch refuses unrelated tracked attributes before writing queue evidence',async t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'xiquan051-unrelated-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}))
  const clone=path.join(root,'clone');fs.mkdirSync(clone)
  const git=args=>{const r=spawnSync('git',['-C',clone,...args],{encoding:'utf8'});assert.equal(r.status,0,r.stderr)}
  git(['init','-b','main']);git(['config','user.email','test@example.invalid']);git(['config','user.name','Archive test'])
  fs.writeFileSync(path.join(clone,'.gitattributes'),'*.zip -text\n');git(['add','.gitattributes']);git(['commit','-m','fixture']);git(['remote','add','origin',archive.repository])
  const unrelated='*.zip text\n';fs.writeFileSync(path.join(clone,'.gitattributes'),unrelated)
  const report=path.join(root,'batch.json')
  await assert.rejects(archive.stageBatch({entries:[]},clone,root,report),/unrelated changes/)
  assert.equal(fs.existsSync(report),false);assert.equal(fs.readFileSync(path.join(clone,'.gitattributes'),'utf8'),unrelated)
})
