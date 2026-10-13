const fs=require('node:fs')
const {fileRecord}=require('./desktop-release.cjs')
const {verifyHttpsFile}=require('./windows-public-recovery.cjs')
const {requestHttpsJson}=require('../../client/electron/https-json.cjs')
async function verify(apk){
  const record=await fileRecord(require('node:path').dirname(apk),require('node:path').basename(apk))
  const origin='https://api.pqxqxy.xyz',url=origin+'/mobile/downloads/xiquan-mobile-ordering-1.2.11.apk'
  const policy=await requestHttpsJson(origin+'/releases/client-policy.json',{allowedOrigin:origin,timeoutMs:60000})
  const config=await requestHttpsJson(origin+'/mobile/download-config.json',{allowedOrigin:origin,timeoutMs:60000})
  if(policy.android.latestVersion!=='1.2.11'||policy.android.latestVersionCode!==18||policy.android.sha256!==record.sha256||policy.android.downloadUrl!==url||config.version!=='1.2.11'||config.versionCode!==18||config.sha256!==record.sha256)throw Error('ANDROID1211_POLICY_MISMATCH')
  await verifyHttpsFile(url,record,{log:console.log})
  return {verified:true,version:'1.2.11',sha256:record.sha256,cloudChanged:false}
}
module.exports={verify}
if(require.main===module)verify(fs.realpathSync(process.argv[2])).then(value=>console.log(JSON.stringify(value))).catch(error=>{console.error(error.message);process.exitCode=1})
