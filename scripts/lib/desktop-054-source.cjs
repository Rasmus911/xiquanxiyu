const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process')
const required=['server/app/wristband_reader_service.py','server/app/api/wristband_reader.py',
  'server/migrations/versions/20261013_wristband_chip.py','client/src/views/WristbandBindingsView.vue',
  'client/src/components/wristbands/WristbandReaderPanel.vue',
  ...['desktop_054_deploy.py','desktop_054_guard.py','desktop_054_pgproof.py','runtime-role.sql'].map(n=>'deploy/cloud/scripts/'+n),
  'scripts/invoke-desktop-054.ps1','scripts/lib/desktop-054-transport.ps1']
function inspectSource(root){
  function git(args){const r=spawnSync('git',args,{cwd:root,encoding:'utf8',windowsHide:true});if(r.status!==0)throw Error('Current source must be committed and clean');return r.stdout}
  const commit=git(['rev-parse','HEAD']).trim();git(['diff','--quiet','HEAD','--','.',':(exclude)mobile/public/download-config.json'])
  const tracked=new Set(git(['ls-files','-z']).split('\0'))
  for(const file of required)if(!tracked.has(file)||!require('./source-security.cjs').allowed(file))throw Error('Required current source missing: '+file)
  const json=name=>JSON.parse(fs.readFileSync(path.join(root,name),'utf8').replace(/^\ufeff/,''))
  const client=json('client/package.json'),lock=json('client/package-lock.json'),mobile=json('mobile/version.json')
  if(client.version!=='0.5.4'||lock.version!=='0.5.4'||lock.packages[''].version!=='0.5.4'||mobile.version!=='1.2.11'||mobile.versionCode!==18||mobile.minimumVersionCode!==9)throw Error('Version identity mismatch')
  return {source_commit:commit,asset_source_commit:commit,schema_head:'20261013_wristband_chip',
    required_migration:'server/migrations/versions/20261013_wristband_chip.py',desktop_version:'0.5.4',
    android_version:'1.2.11',android_version_code:18,targets:['win10-x86','win10-x64','win11-x86','win11-x64']}
}
function assertCloudCompletion(info){
  const receipt=JSON.parse(fs.readFileSync(path.join(info.ProjectRoot,'private/desktop054/completed.json'),'utf8').replace(/^\ufeff/,''))
  if(receipt.phase!=='completed'||receipt.target_schema!=='20261013_wristband_chip'||receipt.source_commit!==info.SourceCommit||receipt.source_sha256!==info.SourceSha256||!/^sha256:[0-9a-f]{64}$/.test(receipt.image_id)||!Object.keys(receipt.origin?.hashes||{}).length)throw Error('Exact completed 0.5.4 cloud receipt required before publication')
  return {verified:true,sourceCommit:receipt.source_commit,image:receipt.image_id}
}
async function delivery(root){
  const file=path.join(root,'交付信息.json'),info=JSON.parse(fs.readFileSync(file,'utf8').replace(/^\ufeff/,''))
  const record=(base,name)=>{const bytes=fs.readFileSync(path.join(base,name));return {file:name,sha256:require('node:crypto').createHash('sha256').update(bytes).digest('hex'),size:bytes.length}}
  info.Files=fs.readdirSync(root).filter(name=>name!=='交付信息.json'&&fs.statSync(path.join(root,name)).isFile()).map(name=>record(root,name))
  // Android build generates this public manifest; APK/signature verification owns it.
  info.ProjectFiles=require('./source-security.cjs').enumerateSourceFiles(info.ProjectRoot)
    .filter(name=>name!=='mobile/public/download-config.json').map(name=>record(info.ProjectRoot,name))
  fs.writeFileSync(file,JSON.stringify(info,null,2)+'\n','utf8')
  return require('./desktop-054.cjs').verifyDelivery(root)
}
module.exports={inspectSource,required,assertCloudCompletion,delivery}
if(require.main===module)(async()=>{
  const [mode,root]=process.argv.slice(2)
  if(mode==='inspect')return inspectSource(root)
  if(mode==='delivery')return delivery(root)
  if(mode==='completed')return assertCloudCompletion(JSON.parse(fs.readFileSync(path.join(root,'交付信息.json'),'utf8').replace(/^\ufeff/,'')))
  throw Error('Unknown 0.5.4 source operation')
})().then(value=>console.log(JSON.stringify(value))).catch(error=>{console.error(error.message);process.exitCode=1})
