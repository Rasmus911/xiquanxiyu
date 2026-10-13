const fs=require('node:fs'),path=require('node:path')
const {verifyHttpsFile}=require('./windows-public-recovery.cjs')
const {requestHttpsJson}=require('../../client/electron/https-json.cjs')
function webManifest(root){
 const names=['index.html','version.json',...fs.readdirSync(path.join(root,'assets')).map(name=>'assets/'+name)]
 return names.map(file=>{const bytes=fs.readFileSync(path.join(root,file));return {file,size:bytes.length,sha256:require('node:crypto').createHash('sha256').update(bytes).digest('hex')}})
}
async function verify(root){
 const info=JSON.parse(fs.readFileSync(path.join(root,'交付信息.json'),'utf8').replace(/^\ufeff/,''))
 if(info.Version!=='0.5.6'||!Array.isArray(info.WebFiles)||!info.WebFiles.length)throw Error('Web manifest missing')
 for(const file of info.WebFiles){
  if(!/^(?:index\.html|version\.json|favicon\.ico|icon\.svg|assets\/[A-Za-z0-9_.-]+\.(?:js|css|png|svg|jpg|woff2?))$/.test(file.file))throw Error('Unexpected web file')
  await verifyHttpsFile('https://api.pqxqxy.xyz/app/'+file.file,file,{log:console.log})
 }
 const health=await requestHttpsJson('https://api.pqxqxy.xyz/api/health',{allowedOrigin:'https://api.pqxqxy.xyz',timeoutMs:60000})
 if(!health.success||health.data?.database!=='ok')throw Error('Public API/database health not confirmed')
 return {verified:true,version:'0.5.6',cloudChanged:false}
}
module.exports={verify,webManifest}
if(require.main===module)(async()=>process.argv[2]==='manifest'?webManifest(process.argv[3]):verify(process.argv[2]))().then(v=>console.log(JSON.stringify(v))).catch(e=>{console.error(e.message);process.exitCode=1})
