const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process')
const repository='https://github.com/Rasmus911/xiquanxiyu',CAP=90*1024*1024,PIECE=32*1024*1024
const roots=new Map([
  ['最新版安装包-账号注册-0.4.9','0.4.9'],['最新版安装包-注册令牌-手机版1.2.8','1.2.8'],
  ['最新版安装包-账号与小票-0.5.0','0.5.0'],
  ['release/windows/0.4.9/registration049-delivery-20261008','0.4.9'],
  ['release/windows/0.5.0/desktop050-final-20261011','0.5.0']
])
const leaves=new Map([
  ['release/README-交付说明.md','0.1.0'],
  ...['6','7','8'].map(n=>['release/mobile/xiquan-mobile-ordering-1.2.'+n+'.apk','1.2.'+n]),
  ...['20261008-182458-f6a90325','20261011-225407-1a104878','20261011-234016-72b2c455','20261011-234408-ea66fa92','20261011-235004-101b8f7a'].map(n=>['release/cloud/xiquan-operations-SOURCE-WEB-'+n+'.zip',n.startsWith('20261008')?'0.4.9':'0.5.0'])
])
function allowed(relative){
  if(typeof relative!=='string'||relative.includes('\\')||relative.includes(':')||relative.split('/').some(p=>!p||p==='.'||p==='..'||p==='private'||p==='.git'||p.startsWith('.env'))||/\.(?:jks|keystore|p12|pfx|key|db|dump|sqlite|backup)$/i.test(relative))return false
  if(relative.endsWith('.pem')&&![...roots.keys()].filter(p=>p.startsWith('release/windows/')).some(p=>relative===p+'/release-public-key.pem'))return false
  return leaves.has(relative)||[...roots.keys()].some(p=>relative.startsWith(p+'/'))
}
function versionFor(relative){return leaves.get(relative)||[...roots].find(([p])=>relative.startsWith(p+'/'))?.[1]}
function safeFile(root,relative){
  if(!allowed(relative))throw Error('Forbidden archive candidate: '+relative)
  const base=path.resolve(root),file=path.resolve(base,relative)
  let current=file
  while(true){if(fs.lstatSync(current).isSymbolicLink())throw Error('Linked archive path refused');if(current===base)break;const parent=path.dirname(current);if(parent===current)throw Error('Escaped archive root');current=parent}
  if(!fs.statSync(file).isFile())throw Error('Only exact leaf files accepted')
  return file
}
async function hashFile(file){const hash=crypto.createHash('sha256');for await(const bytes of fs.createReadStream(file))hash.update(bytes);return hash.digest('hex')}
function category(entry){
  const leaf=path.basename(entry.path),target=/(win(?:10|11)-x(?:86|64))/.exec(entry.path)?.[1]||'shared'
  if(entry.version.startsWith('1.'))return 'mobile/'+entry.version
  if(leaf.endsWith('.zip'))return 'source/'+entry.version
  if(entry.path.startsWith('release/windows/')||leaf.endsWith('.exe'))return 'desktop/'+entry.version+'/'+target
  return 'documents/'+entry.version
}
async function planArchive(root,candidates){
  const entries=[]
  for(const candidate of candidates){
    const relative=candidate.path.replace(/\\/g,'/'),file=safeFile(root,relative),version=versionFor(relative)
    if(candidate.version!==version)throw Error('Wrong archive version')
    entries.push({path:relative,version,size:fs.statSync(file).size,sha256:await hashFile(file),category:category({path:relative,version})})
  }
  return entries
}
async function plan(root){
  const candidates=[]
  function visit(relative){
    const file=path.join(root,relative);if(!fs.existsSync(file))return
    const stat=fs.lstatSync(file);if(stat.isSymbolicLink())throw Error('Linked archive candidate refused')
    if(stat.isDirectory())for(const leaf of fs.readdirSync(file).sort())visit(relative+'/'+leaf)
    else candidates.push({path:relative,version:versionFor(relative)})
  }
  for(const relative of [...roots.keys(),...leaves.keys()])visit(relative)
  return {repository,createdAt:new Date().toISOString(),entries:await planArchive(root,candidates)}
}
async function splitFile(source,destination,prefix,pieceBytes=PIECE){
  if(!Number.isSafeInteger(pieceBytes)||pieceBytes<1||pieceBytes>CAP)throw Error('Invalid piece size')
  const input=fs.openSync(source,'r'),pieces=[];let index=0
  try{
    const buffer=Buffer.alloc(pieceBytes)
    while(true){let count=0,read;while(count<pieceBytes&&(read=fs.readSync(input,buffer,count,pieceBytes-count,null))>0)count+=read
      if(!count)break
      const file=prefix+'.part'+String(++index).padStart(4,'0'),bytes=buffer.subarray(0,count),sha256=crypto.createHash('sha256').update(bytes).digest('hex')
      const target=path.join(destination,file);noLinks(target);fs.mkdirSync(path.dirname(target),{recursive:true})
      if(fs.existsSync(target)){if(await hashFile(target)!==sha256)throw Error('Existing archive part differs')}
      else fs.writeFileSync(target,bytes,{flag:'wx'})
      pieces.push({file,size:count,sha256})
    }
  }finally{fs.closeSync(input)}
  return pieces
}
async function verifyEntryBytes(entry,readBlob){
  const total=crypto.createHash('sha256');let size=0
  if(!Array.isArray(entry.pieces)||!entry.pieces.length)throw Error('Missing ordered pieces')
  for(const piece of entry.pieces){
    if(!/^archive\/objects\/[a-f0-9]{64}(?:\.part\d{4})?$/.test(piece.file)&&!piece.file.startsWith('pieces/'))throw Error('Unsafe remote piece path')
    const bytes=await readBlob(piece.file)
    if(bytes.length!==piece.size||piece.size>CAP||crypto.createHash('sha256').update(bytes).digest('hex')!==piece.sha256)throw Error('Archive piece hash/size differs')
    total.update(bytes);size+=bytes.length
  }
  if(size!==entry.size||total.digest('hex')!==entry.sha256)throw Error('Joined archive hash differs')
}
function partitionObjects(objects,limit=400*1024*1024){
  const batches=[];let batch=[],bytes=0
  for(const object of objects){
    if(object.size>limit||object.size>CAP||object.size<0)throw Error('Object exceeds upload batch cap')
    if(batch.length&&bytes+object.size>limit){batches.push(batch);batch=[];bytes=0}
    batch.push(object);bytes+=object.size
  }
  if(batch.length)batches.push(batch)
  return batches
}
async function stageBatch(input,clone,root,report){
  assertClone(clone)
  const queue=path.join(root,'private/desktop051-archive/upload-queue');noLinks(queue);noLinks(report)
  const attributes=path.join(clone,'.gitattributes');noLinks(attributes)
  let content=fs.existsSync(attributes)?fs.readFileSync(attributes,'utf8'):''
  const withBinaryRule=value=>value.split(/\r?\n/).includes('archive/objects/** -text')?value:value+'\narchive/objects/** -text\n'
  let state
  if(fs.existsSync(report)){
    state=JSON.parse(fs.readFileSync(report,'utf8'))
    if(state.repository!==repository||state.preparedSha256!==crypto.createHash('sha256').update(JSON.stringify(input)).digest('hex'))throw Error('Batch evidence differs')
    if(state.active>=0){
      if(git(clone,['status','--porcelain']).trim())throw Error('Commit current batch through GitHub Desktop before advancing')
      const head=git(clone,['rev-parse','HEAD']).trim(),remote=git(clone,['ls-remote','origin','refs/heads/main']).trim().split(/\s+/)[0]
      if(head!==remote)throw Error('Push current batch through GitHub Desktop before advancing')
      state.pushedCommits.push(head)
    }
  }else{
    const status=git(clone,['status','--porcelain','--untracked-files=all'])
    const tracked=git(clone,['ls-files','--','.gitattributes']).trim()
    const original=tracked?git(clone,['show','HEAD:.gitattributes']):''
    const ownAttributesOnly=content.replace(/\r\n/g,'\n')===withBinaryRule(original).replace(/\r\n/g,'\n')
    if(status.split(/\r?\n/).filter(Boolean).some(line=>!line.startsWith('?? archive/')&&!(['?? .gitattributes',' M .gitattributes'].includes(line)&&ownAttributesOnly)))throw Error('Archive clone has unrelated changes')
    if(withBinaryRule(content)!==content)fs.writeFileSync(attributes,withBinaryRule(content))
    const objects=[...new Map(input.entries.flatMap(r=>r.pieces).map(r=>[r.file,r])).values()].sort((a,b)=>a.file.localeCompare(b.file))
    state={repository,preparedSha256:crypto.createHash('sha256').update(JSON.stringify(input)).digest('hex'),active:-1,batches:partitionObjects(objects),pushedCommits:[]}
    fs.mkdirSync(queue,{recursive:true});fs.writeFileSync(report,JSON.stringify(state,null,2)+'\n')
    for(const object of objects){
      const source=path.join(clone,object.file),target=path.join(queue,path.basename(object.file));noLinks(source);noLinks(target)
      if(await hashFile(source)!==object.sha256)throw Error('Queued source hash differs')
      if(fs.existsSync(target))throw Error('Queue file already exists; evidence retained')
      fs.renameSync(source,target)
    }
  }
  const next=state.active+1
  if(next>=state.batches.length)return {...state,finished:true}
  for(const object of state.batches[next]){
    if(!/^archive\/objects\/[a-f0-9]{64}(?:\.part\d{4})?$/.test(object.file))throw Error('Unsafe batch path')
    const source=path.join(queue,path.basename(object.file)),target=path.join(clone,object.file);noLinks(source);noLinks(target)
    if(await hashFile(source)!==object.sha256||fs.statSync(source).size!==object.size)throw Error('Queued byte identity differs')
    if(fs.existsSync(target))throw Error('Public batch destination already exists')
    fs.renameSync(source,target)
  }
  state.active=next;fs.writeFileSync(report,JSON.stringify(state,null,2)+'\n')
  return {...state,finished:false}
}
function validateProof(entry,proof,now=new Date()){
  if(!allowed(entry.path)||proof.repository!==repository||!/^[a-f0-9]{40}$/.test(proof.remoteCommit))throw Error('Wrong cleanup repository/scope')
  const age=now-new Date(proof.verifiedAt)
  if(!Number.isFinite(age)||age<0||age>86400000)throw Error('Archive proof expired')
  const exact=proof.entries.find(r=>r.path===entry.path)
  if(!exact||JSON.stringify(exact)!==JSON.stringify(entry))throw Error('Exact byte proof missing')
  return entry
}
function git(clone,args,binary=false){
  const r=spawnSync('git',['-C',clone,...args],{encoding:binary?null:'utf8',windowsHide:true,timeout:120000,maxBuffer:CAP+1024*1024})
  if(r.status!==0)throw Error('Archive Git operation failed; local files retained');return r.stdout
}
function noLinks(file){for(let p=path.resolve(file);;){if(fs.existsSync(p)&&fs.lstatSync(p).isSymbolicLink())throw Error('Linked archive destination refused');const parent=path.dirname(p);if(parent===p)break;p=parent}}
function assertClone(clone){noLinks(clone);if(git(clone,['remote','get-url','origin']).trim().replace(/\.git$/,'')!==repository)throw Error('Wrong archive clone')}
async function prepare(input,clone,root){
  assertClone(clone)
  if(git(clone,['status','--porcelain']).trim())throw Error('Archive clone has existing changes; preserve them')
  const trust=require('./operations-release.cjs').trust
  for(const [version,build]of [['0.4.9','registration049-delivery-20261008'],['0.5.0','desktop050-final-20261011']]){
    const folder=path.join(root,'release/windows',version,build)
    if(fs.existsSync(folder))await require('./desktop-release.cjs').verifyReleaseSet(folder,require('./desktop-051.cjs').targets,{mode:'candidate',trust})
  }
  // The whole old packaged trees were created with the same public trust. No keys
  // or environment files qualify; source ZIPs get the existing complete reader.
  // Validate every candidate before creating archive files. A private/invalid
  // late candidate must not leave a half-populated public staging directory.
  for(const entry of input.entries){
    const source=safeFile(root,entry.path)
    if(await hashFile(source)!==entry.sha256)throw Error('Local archive input changed')
    const leaf=path.basename(source),extension=path.extname(source).toLowerCase()
    if(/\.(?:jks|keystore|p12|pfx|key|db|dump|sqlite|backup)$/i.test(leaf)||leaf.startsWith('.env'))throw Error('Private candidate refused')
    if(extension==='.zip')await require('./archive-proof.cjs').scanZip(source)
    else if(['.json','.ps1','.py','.md','.txt','.cjs','.yml','.nsh','.pem'].includes(extension)){
      const content=fs.readFileSync(source,'utf8')
      if(extension==='.pem'&&!content.startsWith('-----BEGIN PUBLIC KEY-----'))throw Error('Only public key permitted')
      require('./source-security.cjs').assertArchiveContentSafe('docs/releases/'+leaf,content)
    }
  }
  const records=[],objects=new Map()
  for(const entry of input.entries){
    const source=safeFile(root,entry.path)
    if(await hashFile(source)!==entry.sha256)throw Error('Local archive input changed')
    let pieces=objects.get(entry.sha256)
    if(!pieces){
      const relative='archive/objects/'+entry.sha256
      noLinks(path.join(clone,relative))
      if(entry.size>CAP)pieces=await splitFile(source,clone,relative)
      else{
        const target=path.join(clone,relative);fs.mkdirSync(path.dirname(target),{recursive:true})
        if(fs.existsSync(target)){if(await hashFile(target)!==entry.sha256)throw Error('Existing archive object differs')}
        else fs.copyFileSync(source,target,fs.constants.COPYFILE_EXCL)
        pieces=[{file:relative,size:entry.size,sha256:entry.sha256}]
      }
      objects.set(entry.sha256,pieces)
    }
    const record={...entry,pieces};await verifyEntryBytes(record,f=>fs.readFileSync(path.join(clone,f)));records.push(record)
  }
  const groups=new Map()
  for(const entry of records){const list=groups.get(entry.category)||[];list.push(entry);groups.set(entry.category,list)}
  for(const [group,entries]of groups){
    const file=path.join(clone,'archive',group,'desktop051-history.json');fs.mkdirSync(path.dirname(file),{recursive:true})
    noLinks(file)
    if(fs.existsSync(file))throw Error('Historical manifest already exists; no overwrite')
    fs.writeFileSync(file,JSON.stringify({repository,format:'ordered-byte-concatenation',entries},null,2)+'\n')
  }
  return {repository,preparedAt:new Date().toISOString(),uploaded:false,entries:records}
}
async function verify(input,clone,root){
  assertClone(clone)
  const commit=git(clone,['ls-remote','origin','refs/heads/main']).trim().split(/\s+/)[0]
  if(!/^[a-f0-9]{40}$/.test(commit))throw Error('Remote commit unavailable')
  git(clone,['fetch','--quiet','origin','main'])
  const read=file=>git(clone,['show',commit+':'+file],true)
  const entries=await verifyRemoteEntries(input,read,async entry=>{
    const local=safeFile(root,entry.path)
    if(fs.statSync(local).size!==entry.size||await hashFile(local)!==entry.sha256)throw Error('Local bytes changed')
  })
  return {repository,remoteCommit:commit,verifiedAt:new Date().toISOString(),entries}
}
async function verifyRemoteEntries(input,read,verifyLocal){
  // Cache small manifests and verified identities, never the multi-GiB blob set.
  const manifests=new Map(),verified=new Set()
  const entries=[]
  for(const entry of input.entries){
    const file='archive/'+entry.category+'/desktop051-history.json'
    if(!manifests.has(file))manifests.set(file,JSON.parse(await read(file)))
    const manifest=manifests.get(file)
    if(manifest.repository!==repository||!manifest.entries.some(row=>JSON.stringify(row)===JSON.stringify(entry)))throw Error('Exact remote category manifest differs')
    const identity=JSON.stringify({size:entry.size,sha256:entry.sha256,pieces:entry.pieces})
    if(!verified.has(identity)){await verifyEntryBytes(entry,read);verified.add(identity)}
    await verifyLocal(entry)
    entries.push(entry)
  }
  return entries
}
module.exports={repository,CAP,PIECE,allowed,planArchive,plan,splitFile,verifyEntryBytes,validateProof,prepare,verify,verifyRemoteEntries,partitionObjects,stageBatch}
if(require.main===module)(async()=>{
  const [mode,root,clone,inputFile,outputFile]=process.argv.slice(2)
  const input=mode==='plan'?null:JSON.parse(fs.readFileSync(inputFile,'utf8').replace(/^\ufeff/,''))
  if(mode==='batch'){
    const r=await stageBatch(input,clone,root,outputFile)
    console.log(JSON.stringify({batch:r.active+1,total:r.batches.length,finished:r.finished,report:outputFile}));return
  }
  if(mode==='eligible'){
    for(const entry of input.entries){validateProof(entry,input);const file=safeFile(root,entry.path);if(fs.statSync(file).size!==entry.size||await hashFile(file)!==entry.sha256)throw Error('Local cleanup bytes changed')}
    console.log('EXACT_FRESH_REMOTE_BYTE_PROOF_OK');return
  }
  const result=mode==='plan'?await plan(root):mode==='prepare'?await prepare(input,clone,root):mode==='verify'?await verify(input,clone,root):null
  if(!result)throw Error('Unknown archive mode')
  fs.writeFileSync(outputFile,JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify({mode,entries:result.entries.length,report:outputFile,remoteCommit:result.remoteCommit,uploaded:result.uploaded}))
})().catch(e=>{console.error(e.message);process.exitCode=1})
