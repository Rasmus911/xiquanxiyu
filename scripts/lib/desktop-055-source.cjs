const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process')
const required=['server/app/inventory_xlsx.py','server/app/inventory_excel_service.py','server/app/api/inventory_excel.py',
  'server/app/wristband_reader_service.py','server/app/api/wristband_reader.py',
  'server/migrations/versions/20261013_manual_inventory_excel.py','client/src/views/WristbandBindingsView.vue',
  'client/src/components/wristbands/WristbandReaderPanel.vue',
  ...['desktop_055_deploy.py','desktop_055_guard.py','desktop_055_pgproof.py','runtime-role.sql'].map(n=>'deploy/cloud/scripts/'+n),
  'scripts/invoke-desktop-055.ps1','scripts/lib/desktop-055-transport.ps1']
function inspectSource(root){
  function git(args){const r=spawnSync('git',args,{cwd:root,encoding:'utf8',windowsHide:true});if(r.status!==0)throw Error('Current source must be committed and clean');return r.stdout}
  const commit=git(['rev-parse','HEAD']).trim();git(['diff','--quiet','HEAD','--','.',':(exclude)mobile/public/download-config.json'])
  const tracked=new Set(git(['ls-files','-z']).split('\0'))
  for(const file of required)if(!tracked.has(file)||!require('./source-security.cjs').allowed(file))throw Error('Required current source missing: '+file)
  const json=name=>JSON.parse(fs.readFileSync(path.join(root,name),'utf8').replace(/^\ufeff/,''))
  const client=json('client/package.json'),lock=json('client/package-lock.json'),mobile=json('mobile/version.json')
  if(client.version!=='0.5.5'||lock.version!=='0.5.5'||lock.packages[''].version!=='0.5.5'||mobile.version!=='1.2.12'||mobile.versionCode!==19||mobile.minimumVersionCode!==9)throw Error('Version identity mismatch')
  return {source_commit:commit,asset_source_commit:commit,schema_head:'20261013_manual_inventory_excel',
    required_migration:'server/migrations/versions/20261013_manual_inventory_excel.py',desktop_version:'0.5.5',
    android_version:'1.2.12',android_version_code:19,targets:['win10-x86','win10-x64','win11-x86','win11-x64']}
}
function assertCloudCompletion(info){
  const receipt=JSON.parse(fs.readFileSync(path.join(info.ProjectRoot,'private/desktop055/completed.json'),'utf8').replace(/^\ufeff/,''))
  if(receipt.phase!=='completed'||receipt.target_schema!=='20261013_manual_inventory_excel'||receipt.source_commit!==info.SourceCommit||receipt.source_sha256!==info.SourceSha256||!/^sha256:[0-9a-f]{64}$/.test(receipt.image_id)||!Object.keys(receipt.origin?.hashes||{}).length)throw Error('Exact completed 0.5.5 cloud receipt required before publication')
  if(info.ServerCorrection){
    const fields=['kind','file','original_sha256','corrected_sha256']
    if(!receipt.server_correction||Object.keys(receipt.server_correction).length!==fields.length||fields.some(key=>receipt.server_correction[key]!==info.ServerCorrection[key]))throw Error('Exact required server correction is not proven by the completed receipt')
  }else if(receipt.server_correction){throw Error('Unreviewed server correction in completion receipt')}
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
  return require('./desktop-055.cjs').verifyDelivery(root)
}
module.exports={inspectSource,required,assertCloudCompletion,delivery}
if(require.main===module)(async()=>{
  const [mode,root]=process.argv.slice(2)
  if(mode==='inspect')return inspectSource(root)
  if(mode==='delivery')return delivery(root)
  if(mode==='completed')return assertCloudCompletion(JSON.parse(fs.readFileSync(path.join(root,'交付信息.json'),'utf8').replace(/^\ufeff/,'')))
  throw Error('Unknown 0.5.5 source operation')
})().then(value=>console.log(JSON.stringify(value))).catch(error=>{console.error(error.message);process.exitCode=1})
