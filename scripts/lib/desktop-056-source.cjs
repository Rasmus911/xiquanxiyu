const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{spawnSync}=require('node:child_process')
const required=['server/app/inventory_xlsx.py','server/app/api/inventory_excel.py','client/electron/assets/xiquan.ico','scripts/lib/desktop-056.cjs','deploy/cloud/scripts/desktop056_format_patch.py','deploy/cloud/scripts/static056_publication.py']
function json(file){return JSON.parse(fs.readFileSync(file,'utf8').replace(/^\ufeff/,''))}
function inspectSource(root){
 const git=args=>{const r=spawnSync('git',args,{cwd:root,encoding:'utf8',windowsHide:true});if(r.status!==0)throw Error('Reviewed source must be committed and clean');return r.stdout}
 const commit=git(['rev-parse','HEAD']).trim();git(['diff','--quiet','HEAD','--','.',':(exclude)mobile/public/download-config.json'])
 const tracked=new Set(git(['ls-files','-z']).split('\0'));for(const file of required)if(!tracked.has(file))throw Error('Missing committed source: '+file)
 const client=json(path.join(root,'client/package.json')),lock=json(path.join(root,'client/package-lock.json')),mobile=json(path.join(root,'mobile/version.json'))
 if(client.version!=='0.5.6'||lock.version!=='0.5.6'||lock.packages[''].version!=='0.5.6'||mobile.version!=='1.2.13'||mobile.versionCode!==20||mobile.minimumVersionCode!==9)throw Error('Release version identity differs')
 return {source_commit:commit,asset_source_commit:commit,schema_head:'20261013_manual_inventory_excel',required_migration:null,desktop_version:'0.5.6',android_version:'1.2.13',android_version_code:20,targets:['win10-x86','win10-x64','win11-x86','win11-x64']}
}
function assertCloudCompletion(info){
 const receipt=json(path.join(info.ProjectRoot,'private/desktop056/completed.json'))
 if(receipt.version!=='0.5.6'||receipt.source_commit!==info.SourceCommit||receipt.api_sha256!==info.ApiSha256||receipt.web_sha256!==info.WebSha256||!/^sha256:[a-f0-9]{64}$/.test(receipt.image_id)||receipt.database_changed!==false||receipt.public_verified!==true)throw Error('Exact cloud 0.5.6 format and web completion receipt required')
 return {verified:true,sourceCommit:info.SourceCommit,image:receipt.image_id,databaseChanged:false}
}
async function delivery(root){
 const file=path.join(root,'交付信息.json'),info=json(file)
 const record=(base,name)=>{const bytes=fs.readFileSync(path.join(base,name));return {file:name,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),size:bytes.length}}
 info.Files=fs.readdirSync(root).filter(name=>name!=='交付信息.json'&&fs.statSync(path.join(root,name)).isFile()).map(name=>record(root,name))
 info.ProjectFiles=require('./source-security.cjs').enumerateSourceFiles(info.ProjectRoot).filter(name=>name!=='mobile/public/download-config.json').map(name=>record(info.ProjectRoot,name))
 fs.writeFileSync(file,JSON.stringify(info,null,2)+'\n');return require('./desktop-056.cjs').verifyDelivery(root)
}
module.exports={required,inspectSource,assertCloudCompletion,delivery}
if(require.main===module)(async()=>{
 const [mode,root]=process.argv.slice(2)
 if(mode==='inspect')return inspectSource(root)
 if(mode==='delivery')return delivery(root)
 if(mode==='completed')return assertCloudCompletion(json(path.join(root,'交付信息.json')))
 throw Error('Unknown desktop056 source operation')
})().then(v=>console.log(JSON.stringify(v))).catch(e=>{console.error(e.message);process.exitCode=1})
