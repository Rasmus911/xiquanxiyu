const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto')
const {spawnSync}=require('node:child_process')
const base=require('./desktop-045.cjs')
const {trust}=require('./operations-release.cjs')
const releaseVersion='0.5.1',schemaHead='20261012_physical_membership'
const releaseNotes=Object.freeze(['增加实体卡消费功能'])
const targets=base.targets
const signingPlan=(options={})=>base.signingPlan({...options,version:releaseVersion})
const verifyCandidates=root=>base.verifyCandidates(root,releaseVersion)
const requiredSource=Object.freeze([
  'server/app/member_cards.py','server/app/member_payment.py','server/app/pass_billing.py',
  'server/app/api/member_cards.py','server/migrations/versions/20261012_physical_membership.py',
  'client/src/components/members/CardScanDialog.vue','client/src/components/members/PhysicalMemberDialog.vue',
  'client/src/components/checkout/MemberPaymentSelector.vue','client/src/components/update/ReleaseHistory.vue',
  'client/src/update/history-data.json',
  ...['desktop_051_deploy.py','desktop_051_guard.py','desktop_051_pgproof.py','operations_backup_verify.py',
    'stock_guard.py','stock_deploy.py','operations_preflight.py','operations_deploy.py','operations_offline_build.py'].map(n=>'deploy/cloud/scripts/'+n),
  'scripts/invoke-desktop-051.ps1','scripts/lib/desktop-051-transport.ps1',
  'scripts/lib/mobile-128-transport.ps1','scripts/lib/desktop-051.cjs'
])
function json(file){return JSON.parse(fs.readFileSync(file,'utf8').replace(/^\ufeff/,''))}
function inspectSource(root){
  function git(args){const r=spawnSync('git',args,{cwd:root,encoding:'utf8',windowsHide:true});if(r.status!==0)throw Error('Source must be committed and clean');return r.stdout}
  const commit=git(['rev-parse','HEAD']).trim();git(['diff','--quiet','HEAD','--'])
  const files=new Set(git(['ls-files','-z']).split('\0'))
  for(const file of requiredSource)if(!files.has(file)||!require('./source-security.cjs').allowed(file))throw Error('Required committed source missing: '+file)
  const pkg=json(path.join(root,'client/package.json')),lock=json(path.join(root,'client/package-lock.json')),mobile=json(path.join(root,'mobile/version.json'))
  if(pkg.version!==releaseVersion||lock.version!==releaseVersion||lock.packages[''].version!==releaseVersion)throw Error('Client/lock version mismatch')
  if(mobile.version!=='1.2.9'||mobile.versionCode!==16)throw Error('Current Android identity changed')
  return {source_commit:commit,asset_source_commit:commit,schema_head:schemaHead,required_migration:'server/migrations/versions/'+schemaHead+'.py',desktop_version:releaseVersion,android_version:mobile.version,android_version_code:mobile.versionCode,targets}
}
async function verifyDeliveryFiles(root,records){
  if(!Array.isArray(records)||!records.length)throw Error('Missing delivery records')
  const seen=new Set(),base=fs.realpathSync(root)
  for(const record of records){
    if(!record||typeof record.file!=='string'||!/^[^/\\:]+$/.test(record.file)||record.file==='.'||record.file==='..'||seen.has(record.file)||!/^[a-f0-9]{64}$/.test(record.sha256))throw Error('Unsafe delivery leaf')
    seen.add(record.file);const file=path.join(base,record.file)
    if(fs.lstatSync(file).isSymbolicLink()||!fs.statSync(file).isFile()||fs.statSync(file).size!==record.size)throw Error('Delivery file size/type mismatch')
    const hash=crypto.createHash('sha256');for await(const bytes of fs.createReadStream(file))hash.update(bytes)
    if(hash.digest('hex')!==record.sha256)throw Error('Delivery file hash mismatch: '+record.file)
  }
}
function validateCompletion(receipt,delivery,state){
  if(receipt.phase!=='completed'||receipt.target_schema!==schemaHead||receipt.source_commit!==delivery.SourceCommit||receipt.source_sha256!==delivery.SourceSha256||!/^sha256:[a-f0-9]{64}$/.test(receipt.image_id)||!Object.keys(receipt.origin?.hashes||{}).length)throw Error('Exact completed source/schema/origin evidence required')
  if(state.image_id!==receipt.image_id||state.api_healthy!==true||state.worker_healthy!==true||state.maintenance!==false)throw Error('Pinned API/worker health and released maintenance required')
  return receipt
}
module.exports={releaseVersion,releaseNotes,targets,trust,schemaHead,signingPlan,verifyCandidates,requiredSource,inspectSource,verifyDeliveryFiles,validateCompletion}
if(require.main===module)(async()=>{
  const [mode,root]=process.argv.slice(2)
  if(mode==='inspect')return inspectSource(root)
  if(mode==='verify-candidates')return verifyCandidates(root)
  if(mode==='verify-delivery'){
    const data=json(path.join(root,'交付信息.json'))
    if(data.Version!==releaseVersion||!/^[a-f0-9]{40}$/.test(data.SourceCommit)||!/^[a-f0-9]{64}$/.test(data.SourceSha256)||!/^[a-f0-9]{64}$/.test(data.CompletionToolSha256)||JSON.stringify(data.Targets)!==JSON.stringify(targets))throw Error('Delivery metadata identity invalid')
    const source=data.Files?.find(r=>r.file===data.SourceZipFile)
    if(!source||source.sha256!==data.SourceSha256||!data.SourceZipFile.endsWith('.zip'))throw Error('SOURCE metadata/hash mismatch')
    if(data.AndroidVersion!=='1.2.9'||data.AndroidVersionCode!==16||data.AndroidSha256!=='d5fdab05253d009319147e6e3775d5d667f2b8a13464cbc44c0caf2130a2472d')throw Error('Android identity mismatch')
    await verifyDeliveryFiles(root,data.Files)
    const apk=crypto.createHash('sha256');for await(const bytes of fs.createReadStream(data.AndroidApkPath))apk.update(bytes)
    if(apk.digest('hex')!==data.AndroidSha256)throw Error('Current Android bytes changed')
    return {verified:true}
  }
  if(mode==='plan')return signingPlan()
  throw Error('Unknown desktop051 operation')
})().then(r=>console.log(JSON.stringify(r))).catch(e=>{console.error(e.message);process.exitCode=1})
