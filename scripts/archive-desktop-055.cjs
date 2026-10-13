// Exact historical public artifacts only. User authorized native Git commit/push.
// No deletion, signing, SSH, database access or modification of current releases.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process')
const base=require('./lib/archive-plan-051.cjs')
const repository=base.repository,root=path.resolve(__dirname,'..'),clone=path.join(root,'private/溪泉版本仓库/xiquanxiyu')
const reports=path.join(root,'private/desktop055-archive'),queue=path.join(reports,'queue')
const directories=new Map([
 ['最新版安装包-刷卡开牌-0.5.4','0.5.4'],
 ['release/windows/0.5.4','0.5.4'],
])
const leaves=new Map([
 ['release/cloud/xiquan-desktop054-SOURCE-WEB-20261013-115235-9bf0698f.zip','0.5.4'],
])
function versionFor(name){
 if(typeof name!=='string'||name.includes('\\')||name.includes(':')||name.split('/').some(p=>!p||p==='.'||p==='..'||p==='private'||p==='.git'||p.startsWith('.env'))||/\.(?:jks|keystore|p12|pfx|key|db|dump|sqlite|backup)$/i.test(name))throw Error('Forbidden archive path')
 const version=leaves.get(name)||[...directories].find(([prefix])=>name.startsWith(prefix+'/'))?.[1]
 if(!version)throw Error('Path is not an exact historical artifact')
 if(name.endsWith('.pem')&&!(name==='最新版安装包-刷卡开牌-0.5.4/release-public-key.pem'||
   (name.startsWith('release/windows/')&&name.endsWith('/release-public-key.pem'))))throw Error('Only original release public key allowed')
 return version
}
function safe(file){
 let cursor=path.resolve(file)
 while(true){if(fs.existsSync(cursor)&&fs.lstatSync(cursor).isSymbolicLink())throw Error('Linked archive path');const parent=path.dirname(cursor);if(parent===cursor)break;cursor=parent}
 return path.resolve(file)
}
function git(args,binary=false){const result=spawnSync('git',['-C',clone,...args],{encoding:binary?null:'utf8',windowsHide:true,timeout:120000,maxBuffer:96*1024*1024});if(result.status!==0)throw Error('Archive Git '+args[0]+' failed; originals retained');return result.stdout}
function assertClone(){safe(clone);if(git(['remote','get-url','origin']).trim().replace(/\.git$/,'')!==repository)throw Error('Wrong archive repository')}
async function hash(file){const digest=crypto.createHash('sha256');for await(const data of fs.createReadStream(safe(file)))digest.update(data);return digest.digest('hex')}
function json(file,data){safe(file);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,JSON.stringify(data,null,2)+'\n')}
function read(name){return JSON.parse(fs.readFileSync(path.join(reports,name),'utf8'))}
function category(name,version){
 if(version.startsWith('1.'))return 'mobile/'+version
 if(name.endsWith('.zip'))return 'source/'+version
 if(name.startsWith('release/windows/')||name.endsWith('.exe'))return 'desktop/'+version+'/'+(/win(?:10|11)-x(?:86|64)/.exec(name)?.[0]||'shared')
 return 'documents/'+version
}
async function plan(){
 const entries=[]
 async function visit(name){const file=safe(path.join(root,name));if(!fs.existsSync(file))return;const stat=fs.lstatSync(file)
  if(stat.isDirectory()){for(const leaf of fs.readdirSync(file).sort())await visit(name+'/'+leaf);return}
  if(!stat.isFile())throw Error('Not a regular archive artifact')
  const version=versionFor(name)
  entries.push({path:name,version,category:category(name,version),size:stat.size,sha256:await hash(file)})
 }
 for(const prefix of [...directories.keys(),...leaves.keys()])await visit(prefix)
 const document={repository,createdAt:new Date().toISOString(),entries};json(path.join(reports,'plan.json'),document)
 console.log(JSON.stringify({entries:entries.length,bytes:entries.reduce((sum,row)=>sum+row.size,0),plan:path.join(reports,'plan.json')}))
}
async function prepare(){
 assertClone();if(git(['status','--porcelain']).trim())throw Error('Archive clone has changes; preserve them')
 if(fs.existsSync(path.join(reports,'prepared.json')))throw Error('Preparation already retained; use batch/verify, not another prepare')
 const input=read('plan.json');if(input.repository!==repository)throw Error('Plan repository differs')
 // Scan the complete allowed input before putting any new bytes into the public clone.
 for(const entry of input.entries){const file=safe(path.join(root,entry.path));if(versionFor(entry.path)!==entry.version||fs.statSync(file).size!==entry.size||await hash(file)!==entry.sha256)throw Error('Historical source changed')
  const extension=path.extname(file).toLowerCase()
  if(extension==='.zip')await require('./lib/archive-proof.cjs').scanZip(file)
  else if(['.json','.ps1','.py','.md','.txt','.cjs','.js','.yml','.nsh','.pem','.html','.xml'].includes(extension)){
   const text=fs.readFileSync(file,'utf8');if(extension==='.pem'&&!text.startsWith('-----BEGIN PUBLIC KEY-----'))throw Error('Private key refused')
   require('./lib/source-security.cjs').assertArchiveContentSafe('docs/releases/'+path.basename(file),text)
  }
 }
 const objects=new Map(),entries=[],pending=[],reused=new Map();fs.mkdirSync(queue,{recursive:true})
 // Reuse only hash-described pieces already tracked in this exact public clone.
 // Full joined identities are independently checked below, before any upload.
 for(const name of git(['ls-files','-z','--','archive']).split('\0').filter(name=>name.endsWith('.json'))){
  const document=JSON.parse(fs.readFileSync(safe(path.join(clone,name)),'utf8').replace(/^\ufeff/,''))
  for(const piece of (Array.isArray(document.entries)?document.entries:[]).flatMap(entry=>Array.isArray(entry.pieces)?entry.pieces:[])){
   if(/^archive\/objects\/[a-f0-9]{64}(?:\.part\d{4})?$/.test(piece.file)&&/^[a-f0-9]{64}$/.test(piece.sha256)&&piece.size<=base.PIECE&&fs.existsSync(safe(path.join(clone,piece.file))))reused.set(piece.sha256,piece)
  }
 }
 for(const entry of input.entries){let pieces=objects.get(entry.sha256)
  if(!pieces){const prefix='archive/objects/'+entry.sha256
   pieces=await base.splitFile(path.join(root,entry.path),queue,entry.sha256,base.PIECE)
   if(!pieces.length){const name=entry.sha256+'.part0001';fs.writeFileSync(path.join(queue,name),Buffer.alloc(0),{flag:'wx'});pieces=[{file:name,size:0,sha256:entry.sha256}]}
   const compact=[]
   for(const piece of pieces){
    let record=reused.get(piece.sha256)
    if(record){if(record.size!==piece.size||await hash(path.join(clone,record.file))!==piece.sha256)throw Error('Existing archive chunk differs')}
    else{
     record={...piece,file:'archive/objects/'+piece.sha256}
     const source=path.join(queue,piece.file),target=path.join(queue,piece.sha256)
     if(fs.existsSync(target)){if(await hash(target)!==piece.sha256)throw Error('Private chunk differs')}
     else fs.copyFileSync(source,target,fs.constants.COPYFILE_EXCL)
    }
    compact.push(record)
   }
   pieces=compact
   for(const piece of pieces){const exists=safe(path.join(clone,piece.file));if(fs.existsSync(exists)){if(fs.statSync(exists).size!==piece.size||await hash(exists)!==piece.sha256)throw Error('Existing remote object differs')}else if(!pending.some(row=>row.file===piece.file))pending.push(piece)}
   await base.verifyEntryBytes({...entry,pieces},async file=>fs.readFileSync(fs.existsSync(path.join(clone,file))?path.join(clone,file):path.join(queue,path.basename(file))))
   objects.set(entry.sha256,pieces)
  }
  entries.push({...entry,pieces})
 }
 const document={repository,preparedAt:new Date().toISOString(),entries}
 json(path.join(reports,'prepared.json'),document)
 const groups=new Map();for(const entry of entries){const rows=groups.get(entry.category)||[];rows.push(entry);groups.set(entry.category,rows)}
 for(const [group,rows]of groups){const destination=path.join(clone,'archive',group,'history-for-055.json');if(fs.existsSync(destination))throw Error('Historical category already exists');json(destination,{repository,format:'ordered-byte-concatenation',entries:rows})}
 const attributes=fs.readFileSync(path.join(clone,'.gitattributes'),'utf8');if(!attributes.includes('archive/objects/** -text'))throw Error('Binary archive attribute missing')
 const batches=base.partitionObjects(pending,200*1024*1024)
 json(path.join(reports,'batches.json'),{repository,active:-1,batches,pushedCommits:[]})
 console.log(JSON.stringify({prepared:true,entries:entries.length,pendingObjects:pending.length,batches:batches.length,uploaded:false}))
}
async function batch(){
 assertClone();const state=read('batches.json');if(state.repository!==repository)throw Error('Batch repository differs')
 if(state.active>=0){if(git(['status','--porcelain']).trim())throw Error('Commit current archive batch using authorized Git first')
  const head=git(['rev-parse','HEAD']).trim(),remote=git(['ls-remote','origin','refs/heads/main']).trim().split(/\s+/)[0];if(head!==remote)throw Error('Push current batch using authorized Git first');state.pushedCommits.push(head)
 }
 const next=state.active+1;if(next>=state.batches.length){console.log('ALL_ARCHIVE_BATCHES_PUSHED');return}
 for(const piece of state.batches[next]){if(!/^archive\/objects\/[a-f0-9]{64}(?:\.part\d{4})?$/.test(piece.file))throw Error('Unsafe archive piece')
  const source=safe(path.join(queue,path.basename(piece.file))),destination=safe(path.join(clone,piece.file))
  if(fs.statSync(source).size!==piece.size||await hash(source)!==piece.sha256||fs.existsSync(destination))throw Error('Queued archive piece changed')
  fs.mkdirSync(path.dirname(destination),{recursive:true});fs.copyFileSync(source,destination,fs.constants.COPYFILE_EXCL)
 }
 state.active=next;json(path.join(reports,'batches.json'),state);console.log(JSON.stringify({batch:next+1,total:state.batches.length,bytes:state.batches[next].reduce((sum,row)=>sum+row.size,0),commitAndPush:'authorized Git commit/push'}))
}
async function verify(){
 assertClone();if(git(['status','--porcelain']).trim())throw Error('Archive has uncommitted files')
 const remote=git(['ls-remote','origin','refs/heads/main']).trim().split(/\s+/)[0]
 if(!/^[a-f0-9]{40}$/.test(remote)||git(['rev-parse','HEAD']).trim()!==remote)throw Error('Remote has not received the exact archive commit')
 const prepared=read('prepared.json'),manifestCache=new Map(),identityCache=new Set()
 for(const entry of prepared.entries){const manifestName='archive/'+entry.category+'/history-for-055.json'
  if(!manifestCache.has(manifestName))manifestCache.set(manifestName,JSON.parse(git(['show',remote+':'+manifestName],true)))
  const manifest=manifestCache.get(manifestName);if(manifest.repository!==repository||!manifest.entries.some(row=>JSON.stringify(row)===JSON.stringify(entry)))throw Error('Exact remote category differs')
  if(!identityCache.has(entry.sha256)){await base.verifyEntryBytes(entry,async file=>git(['show',remote+':'+file],true));identityCache.add(entry.sha256)}
  if(versionFor(entry.path)!==entry.version||fs.statSync(path.join(root,entry.path)).size!==entry.size||await hash(path.join(root,entry.path))!==entry.sha256)throw Error('Local historical original changed')
 }
 json(path.join(reports,'remote-proof.json'),{...prepared,remoteCommit:remote,verifiedAt:new Date().toISOString(),originalsDeleted:false})
 console.log(JSON.stringify({remoteByteProof:true,remoteCommit:remote,entries:prepared.entries.length,originalsDeleted:false}))
}
function validateCleanup(entry,proof,now=new Date()){
 const age=now-new Date(proof.verifiedAt)
 if(proof.repository!==repository||!/^[a-f0-9]{40}$/.test(proof.remoteCommit)||!Number.isFinite(age)||age<0||age>86400000)throw Error('Wrong or expired remote proof')
 if(versionFor(entry.path)!==entry.version||!Number.isSafeInteger(entry.size)||entry.size<0||!/^[a-f0-9]{64}$/.test(entry.sha256)||!Array.isArray(entry.pieces)||!entry.pieces.length||!proof.entries.some(row=>JSON.stringify(row)===JSON.stringify(entry)))throw Error('Exact cleanup identity missing')
 return true
}
async function eligible(){
 assertClone();const proof=read('remote-proof.json')
 const remote=git(['ls-remote','origin','refs/heads/main']).trim().split(/\s+/)[0]
 if(remote!==proof.remoteCommit)throw Error('Remote changed; verify again before cleanup')
 for(const entry of proof.entries){validateCleanup(entry,proof);const file=safe(path.join(root,entry.path));if(!fs.statSync(file).isFile()||fs.statSync(file).size!==entry.size||await hash(file)!==entry.sha256)throw Error('Local cleanup bytes changed')}
 console.log('EXACT_055_ARCHIVE_PROOF_AND_LOCAL_BYTES_VERIFIED; no deletion performed')
}
module.exports={versionFor,category,validateCleanup}
if(require.main===module)(async()=>{const mode=process.argv[2];if(mode==='plan')return plan();if(mode==='prepare')return prepare();if(mode==='batch')return batch();if(mode==='verify')return verify();if(mode==='eligible')return eligible();throw Error('Unknown archive mode; no deletion supported')})().catch(error=>{console.error(error.message);process.exitCode=1})
