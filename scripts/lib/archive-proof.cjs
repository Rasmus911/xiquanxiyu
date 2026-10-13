const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto')
const {spawnSync}=require('node:child_process')
const repository='https://github.com/Rasmus911/xiquanxiyu'
const oldCloud='xiquan-operations-SOURCE-WEB-20261008-182458-f6a90325.zip'
function permittedCandidate(file,root){
  if(typeof file!=='string'||!path.win32.isAbsolute(file)||file.includes('..')||file.includes(':',2))return false
  const relative=path.win32.relative(root,file).replace(/\\/g,'/')
  if(!relative||relative.startsWith('../')||path.win32.isAbsolute(relative))return false
  return /^最新版安装包-账号注册-0\.4\.9\/[^/]+$/.test(relative)
    || /^最新版安装包-注册令牌-手机版1\.2\.8\/[^/]+$/.test(relative)
    || /^release\/windows\/0\.4\.9\/[^/]+\/.+[^/]$/.test(relative)
    || /^release\/mobile\/xiquan-mobile-ordering-1\.2\.[678]\.apk$/.test(relative)
    || relative==='release/cloud/'+oldCloud
}
function eligibleCleanup(entry,proof,{root,now=new Date()}={}){
  if(!permittedCandidate(entry.absolutePath,root)||proof.repository!==repository)throw Error('Forbidden cleanup scope')
  if(!/^\d+\.\d+\.\d+$/.test(entry.version)||! /^[0-9a-f]{40}$/.test(entry.sourceCommit)
    ||!Number.isSafeInteger(entry.size)||entry.size<0||!/^[0-9a-f]{64}$/.test(entry.sha256)
    ||entry.remoteSha256!==entry.sha256)throw Error('Invalid archive identity')
  const age=now-new Date(entry.verifiedAt)
  if(!Number.isFinite(age)||age<0||age>86400000)throw Error('Archive proof expired')
  if(!new RegExp('^https://github\\.com/Rasmus911/xiquanxiyu/(?:blob/[0-9a-f]{40}/archive/|releases/download/[^/]+/)[^?#]+$').test(entry.remoteUrl))throw Error('Wrong remote repository')
  const match=proof.entries?.find(row=>row.absolutePath===entry.absolutePath)
  if(!match||['version','sourceCommit','size','sha256','remoteSha256','remoteUrl','verifiedAt'].some(key=>match[key]!==entry[key]))throw Error('Exact remote proof missing')
  return entry
}
function safeFile(file,root){
  file=path.resolve(file);root=path.resolve(root)
  if(!permittedCandidate(file,root))throw Error('Forbidden archive file: '+file)
  let cursor=file
  while(cursor!==root){if(fs.lstatSync(cursor).isSymbolicLink())throw Error('Reparse file refused');const parent=path.dirname(cursor);if(parent===cursor)throw Error('Archive path escaped its root');cursor=parent}
  if(!fs.statSync(file).isFile())throw Error('An individual file is required')
}
async function hashFile(file){const hash=crypto.createHash('sha256');for await(const chunk of fs.createReadStream(file))hash.update(chunk);return hash.digest('hex')}
async function plan(root){
  const entries=[]
  const ownerCommit='4f11626373298754d2e0ceacd82ae7ff5dd71204'
  async function visit(file,version){
    if(!fs.existsSync(file)||fs.lstatSync(file).isSymbolicLink())return
    if(fs.statSync(file).isDirectory()){for(const name of fs.readdirSync(file).sort()){if(name==='__pycache__')continue;await visit(path.join(file,name),version)}return}
    safeFile(file,root)
    entries.push({version,sourceCommit:ownerCommit,absolutePath:file,size:fs.statSync(file).size,sha256:await hashFile(file)})
  }
  for(const [name,version] of [['最新版安装包-账号注册-0.4.9','0.4.9'],['最新版安装包-注册令牌-手机版1.2.8','1.2.8'],['release/windows/0.4.9','0.4.9'],['release/cloud/'+oldCloud,'0.4.9']])await visit(path.join(root,name),version)
  for(const version of ['1.2.6','1.2.7','1.2.8'])await visit(path.join(root,'release/mobile/xiquan-mobile-ordering-'+version+'.apk'),version)
  return {repository,createdAt:new Date().toISOString(),entries}
}
function git(clone,args,encoding='utf8',maxBuffer=96*1024*1024){const r=spawnSync('git',['-C',clone,...args],{encoding,maxBuffer,timeout:120000,windowsHide:true});if(r.status!==0)throw Error('Archive Git '+args[0]+' failed ('+(r.error?.code??r.status)+'); local files retained');return r.stdout}
function blob(clone,commit,file){return git(clone,['show',commit+':'+file],null)}
async function verify(input,clone,root){
  if(git(clone,['remote','get-url','origin']).trim().replace(/\.git$/,'')!==repository)throw Error('Wrong archive clone')
  const head=git(clone,['ls-remote','origin','refs/heads/main']).trim().split(/\s+/)[0]
  if(!/^[0-9a-f]{40}$/.test(head))throw Error('Remote commit unavailable')
  const cached=spawnSync('git',['-C',clone,'cat-file','-e',head+'^{commit}'],{windowsHide:true,timeout:15000})
  if(cached.status!==0)git(clone,['fetch','--quiet','origin','main'])
  if(git(clone,['rev-parse',head+'^{commit}']).trim()!==head)throw Error('Exact remote object unavailable')
  console.log('ARCHIVE_REMOTE_COMMIT_VERIFIED='+head)
  const listing=git(clone,['ls-tree','-rlz',head,'--','archive']).split('\0').filter(Boolean).map(line=>{
    const match=/^[0-9]+ blob [0-9a-f]+\s+(\d+)\t([\s\S]+)$/.exec(line);return match?{size:Number(match[1]),file:match[2]}:null
  }).filter(Boolean)
  const sizes=new Set(input.entries.map(row=>row.size)),hashes=new Map()
  for(const item of listing.filter(row=>sizes.has(row.size)&&row.size<=90*1024*1024&&!row.file.endsWith('.part001')&&!/\.part\d+$/.test(row.file))){
    const bytes=blob(clone,head,item.file)
    if(bytes.length!==item.size)throw Error('Remote archive size differs')
    hashes.set(crypto.createHash('sha256').update(bytes).digest('hex'),item.file)
  }
  const manifestFile='archive/desktop/0.4.9/installers/parts-manifest.json'
  const manifest=JSON.parse(blob(clone,head,manifestFile).toString('utf8').replace(/^\ufeff/,''))
  if(manifest.format!=='byte-concatenation'||manifest.version!=='0.4.9')throw Error('Remote parts format differs')
  for(const item of manifest.installers){
    if(!input.entries.some(row=>row.sha256===item.sha256&&row.size===item.bytes))continue
    const hash=crypto.createHash('sha256');let size=0
    for(const part of item.parts){
      if(!/^Xiquan-Bathhouse-Setup-0\.4\.9-win(?:10|11)-x(?:86|64)\.exe\.part\d+$/.test(part.name))throw Error('Invalid remote part')
      const bytes=blob(clone,head,'archive/desktop/0.4.9/installers/'+part.name)
      if(bytes.length!==part.bytes||crypto.createHash('sha256').update(bytes).digest('hex')!==part.sha256)throw Error('Remote part hash mismatch')
      hash.update(bytes);size+=bytes.length
    }
    if(size!==item.bytes||hash.digest('hex')!==item.sha256)throw Error('Remote joined installer differs')
    hashes.set(item.sha256,manifestFile)
  }
  const verifiedAt=new Date().toISOString(),entries=[],retained=[]
  for(const entry of input.entries){
    safeFile(entry.absolutePath,root)
    if(fs.statSync(entry.absolutePath).size!==entry.size||await hashFile(entry.absolutePath)!==entry.sha256)throw Error('Local file changed; retain all')
    const remote=hashes.get(entry.sha256)
    if(remote)entries.push({...entry,remoteSha256:entry.sha256,remoteUrl:repository+'/blob/'+head+'/'+remote,verifiedAt})
    else retained.push(entry)
  }
  return {repository,remoteCommit:head,verifiedAt,entries,retained}
}
async function scanZip(file){
  const result=spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',path.join(__dirname,'archive-zip-read.ps1'),'-ZipPath',file],{encoding:'utf8',maxBuffer:96*1024*1024,timeout:90000,windowsHide:true})
  if(result.status!==0)throw Error('Historical ZIP complete-read check failed; retained')
  const records=JSON.parse(result.stdout),names=new Set();let bytes=0
  if(!Array.isArray(records)||records.length>5000)throw Error('Invalid historical ZIP listing')
  for(const entry of records){
    const relative=entry.name.replace(/^xiquan\//,'')
    if(names.has(entry.name)||relative.startsWith('/')||relative.includes(':')||relative.split('/').some(part=>part==='..'||part==='private'||part==='.git'||part==='node_modules')||/\\|\.env$|\.(?:jks|p12|key|db|sqlite|dump|backup|apk|exe)$/i.test(relative)||!Number.isSafeInteger(entry.size)||entry.size<0||entry.size>16*1024*1024)throw Error('Unsafe historical ZIP path/content; retained')
    names.add(entry.name)
    const data=Buffer.from(entry.data,'base64');bytes+=data.length
    if(data.length!==entry.size||bytes>64*1024*1024)throw Error('Historical ZIP incomplete/oversized content; retained')
    if(!entry.name.endsWith('/')&&!/\.(?:png|jpg|jar|woff2?)$/.test(relative))require('./source-security.cjs').assertArchiveContentSafe(relative,data.toString('utf8'))
  }
  return {entries:records.length,bytes}
}
function archiveDestination(entry){return 'archive/'+(entry.version.startsWith('1.')?'android':'desktop')+'/'+entry.version+'/delivery-20261011/'+path.basename(entry.absolutePath)}
async function assertPreparedChanges(clone,status,expected){
  async function check(file){
    const absolute=path.join(clone,file)
    if(fs.lstatSync(absolute).isSymbolicLink())throw Error('Archive reparse target refused')
    if(fs.statSync(absolute).isDirectory()){for(const name of fs.readdirSync(absolute))await check(file.replace(/\/$/,'')+'/'+name);return}
    if(file==='archive/maintenance/2026-10-11/remaining-history.json'){
      const index=JSON.parse(fs.readFileSync(absolute,'utf8'))
      if(index.repository!==repository||index.uploaded!==false||index.latestDesktop!=='0.5.0'||index.latestAndroid!=='1.2.9'||!Array.isArray(index.copied)||!Array.isArray(index.retained)||Object.keys(index).some(key=>!['repository','preparedAt','uploaded','latestDesktop','latestAndroid','copied','retained'].includes(key)))throw Error('Existing archive index differs; preserve it')
      if(index.copied.some(row=>expected.get(row.archivePath)!==row.sha256))throw Error('Existing archive index has different inputs; preserve it')
      return
    }
    if(!expected.has(file)||await hashFile(absolute)!==expected.get(file))throw Error('Archive clone has unrelated or changed content; preserve it')
  }
  for(const line of status.split('\0').filter(Boolean)){
    if(!line.startsWith('?? '))throw Error('Archive clone has tracked changes; preserve them')
    const file=line.slice(3)
    if(!/^archive\/(?:desktop\/0\.4\.9|android\/1\.2\.[678])\/delivery-20261011\//.test(file)&&!['archive/maintenance/','archive/maintenance/2026-10-11/','archive/maintenance/2026-10-11/remaining-history.json'].includes(file))throw Error('Archive clone has unrelated changes; preserve them')
    await check(file)
  }
}
async function prepare(proof,clone,root){
  const expected=new Map(proof.retained.map(entry=>[archiveDestination(entry),entry.sha256]))
  await assertPreparedChanges(clone,git(clone,['status','--porcelain','-z']),expected)
  const copied=[],retained=[]
  for(const entry of proof.retained){
    const relative=path.relative(root,entry.absolutePath).replace(/\\/g,'/'),leaf=path.basename(entry.absolutePath)
    if(relative.startsWith('release/windows/')||entry.size>90*1024*1024){retained.push({...entry,reason:'Derived build material or large asset; not added to ordinary Git'});continue}
    safeFile(entry.absolutePath,root)
    if(await hashFile(entry.absolutePath)!==entry.sha256)throw Error('Local archive input changed')
    try{
      if(leaf.endsWith('.zip'))await scanZip(entry.absolutePath,root)
      else if(!leaf.endsWith('.apk'))require('./source-security.cjs').assertArchiveContentSafe('docs/releases/'+leaf,fs.readFileSync(entry.absolutePath,'utf8'))
    }catch(error){retained.push({...entry,reason:'Content review required; not copied to public clone'});continue}
    const destination=archiveDestination(entry)
    const file=path.join(clone,destination)
    if(fs.existsSync(file)&&await hashFile(file)!==entry.sha256)throw Error('Existing archive target differs; not overwritten')
    fs.mkdirSync(path.dirname(file),{recursive:true});fs.copyFileSync(entry.absolutePath,file)
    copied.push({...entry,archivePath:destination})
  }
  const result={repository,preparedAt:new Date().toISOString(),uploaded:false,latestDesktop:'0.5.0',latestAndroid:'1.2.9',copied,retained}
  const index=path.join(clone,'archive/maintenance/2026-10-11/remaining-history.json')
  fs.mkdirSync(path.dirname(index),{recursive:true});fs.writeFileSync(index,JSON.stringify(result,null,2)+'\n')
  return result
}
module.exports={eligibleCleanup,permittedCandidate,plan,verify,prepare,scanZip,assertPreparedChanges}
if(require.main===module)(async()=>{
  const [mode,root,clone,inputFile,outputFile]=process.argv.slice(2)
  if(mode==='eligible'){
    const proof=JSON.parse(fs.readFileSync(inputFile,'utf8').replace(/^\ufeff/,''))
    for(const entry of proof.entries)eligibleCleanup(entry,proof,{root})
    process.stdout.write('EXACT_ARCHIVE_PROOF_VALID\n');return
  }
  let result
  if(mode==='plan')result=await plan(root)
  else{const input=JSON.parse(fs.readFileSync(inputFile,'utf8').replace(/^\ufeff/,''));result=mode==='verify'?await verify(input,clone,root):mode==='prepare'?await prepare(input,clone,root):null}
  if(!result)throw Error('Unknown archive mode')
  fs.writeFileSync(outputFile,JSON.stringify(result,null,2)+'\n')
  console.log(JSON.stringify({mode,report:outputFile,verified:result.entries?.length,copied:result.copied?.length,retained:result.retained?.length,remoteCommit:result.remoteCommit,uploaded:result.uploaded}))
})().catch(error=>{console.error(error.message);process.exitCode=1})
