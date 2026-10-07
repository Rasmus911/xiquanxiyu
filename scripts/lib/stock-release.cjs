const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const { targetIds, getTarget } = require('../../client/electron/target-profiles.cjs')
const { verifySignedRelease } = require('../../client/electron/desktop-release.cjs')
const { compareSemver } = require('../../client/electron/update-policy.cjs')
const { verifyReleaseSet, fileRecord } = require('./desktop-release.cjs')
const { checkedFile, trust } = require('./operations-release.cjs')
const { readSourceArchive } = require('./stock-source.cjs')
const originalAndroid = Object.freeze({package:'com.xiquan.mobileordering',version:'1.2.3',version_code:10,
  certificate_sha256:'15257f00ccafcabfbac7c105b3a4606127f4d04afa55e44994171994a1ce50e9',
  previous_sha256:'869e52d5d76265591ff7936f27706eacbb690df5afb7952a11b128eeba6af04c'})
function validateAndroid(record) {
  if (!record || Object.entries(originalAndroid).some(([key,value]) => record[key] !== value)) throw Error('Actual Android identity/original certificate evidence required')
}
function validateIdentity(m, production=false) {
  if (!m || m.schema !== 1 || m.trust_key_id !== trust.keyId || m.testOnly === true) throw Error('Stock original trust required')
  if (!/^[0-9a-f]{40}$/.test(m.source_commit) || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$/.test(m.build_id)) throw Error('Stock source commit/build identity invalid')
  if(m.desktop_version !== '0.4.4' || m.android_version !== '1.2.3' || m.android_version_code !== 10) throw Error('Stock version mismatch')
  if (!Array.isArray(m.targets) || m.targets.length !== 6 || new Set(m.targets.map(r=>r.target)).size !== 6 || targetIds.some(id=>!m.targets.some(r=>r.target===id))) throw Error('Exactly six stock targets required')
  for (const row of m.targets) {
    const profile = getTarget(row.target)
    if (row.runtime !== profile.electronVersion || row.arch !== profile.arch || row.file !== `${row.target}/Xiquan-Bathhouse-Setup-0.4.4-${row.target}.exe`) throw Error('Stock target runtime/arch/file mismatch')
  }
  if (!['candidate','production'].includes(m.mode)) throw Error('Stock manifest mode invalid')
  if (m.android) validateAndroid(m.android)
  if (production && (m.mode !== 'production' || !m.android)) throw Error('Stock candidate/pending cannot be published')
}
async function collectWindows(root,mode='candidate') {
  const index = await verifyReleaseSet(root,targetIds,{mode,trust})
  if (index.version !== '0.4.4') throw Error('Actual stock payload version mismatch')
  return index.targets.map(report => ({target:report.profile.targetId,arch:report.payloadArch,runtime:report.profile.electronVersion,
    build_id:report.buildId,file:`${report.profile.targetId}/${report.artifact.fileName}`,size:report.artifact.size,sha256:report.artifact.sha256,
    blockmap:{file:`${report.profile.targetId}/${report.blockmap.fileName}`,size:report.blockmap.size,sha256:report.blockmap.sha256},
    updater_manifest:{file:`${report.profile.targetId}/${report.updaterManifest.fileName}`,size:report.updaterManifest.size,sha256:report.updaterManifest.sha256}}))
}
async function signingPlan(readPolicy = async id => {
  const response = await fetch(`https://api.pqxqxy.xyz/releases/desktop/${id}.json`,{cache:'no-store',signal:AbortSignal.timeout(15000)})
  if (!response.ok) throw Error(`Previous signed policy unavailable: ${id} HTTP ${response.status}; no bootstrap assumed`)
  return response.json()
}) {
  const previous = []
  for (const id of targetIds) {
    const envelope = await readPolicy(id)
    const release = verifySignedRelease(envelope,{trust,profile:getTarget(id),currentVersion:'0.4.4'})
    if(compareSemver(release.desktop.latestVersion,'0.4.4')>=0) throw Error(`Previous ${id} version is not older; fresh release/version review required`)
    previous.push({target:id,sequence:release.sequence,minimum_version:release.desktop.minimumVersion,envelope})
  }
  const sequence = Math.max(...previous.map(row=>row.sequence))+1
  if (!Number.isSafeInteger(sequence) || sequence > 2147483647) throw Error('Sequence exhausted')
  return {schema:1,checked_at:new Date().toISOString(),trust_key_id:trust.keyId,sequence,previous}
}
function inspectAndroid(root, record, previousApk) {
  validateAndroid(record)
  const apk = checkedFile(root,record,new Set())
  if (!previousApk) throw Error('Original previous APK required for fresh certificate comparison')
  const result = spawnSync('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-File',path.join(__dirname,'stock-mobile.ps1'),
    '-ApkPath',apk,'-PreviousApkPath',previousApk],{encoding:'utf8',windowsHide:true})
  if(result.status!==0) throw Error('Fresh original Android certificate check failed: '+result.stderr)
}
async function validateManifest(root,m,{production=false,previousApk}={}) {
  validateIdentity(m,production)
  const rows = await collectWindows(root,production?'release':'candidate'), seen = new Set()
  for(const row of m.targets) {
    const actual=rows.find(r=>r.target===row.target)
    if(actual.build_id!==m.build_id || JSON.stringify(actual)!==JSON.stringify(row)) throw Error('Actual six payload/manifest mismatch')
    for(const record of [row,row.blockmap,row.updater_manifest]) checkedFile(root,record,seen)
  }
  const zip=checkedFile(root,m.source_web,seen)
  const contract=await readSourceArchive(zip,m.source_commit)
  if(JSON.stringify(contract)!==JSON.stringify(m.source_contract)) throw Error('Actual SOURCE/WEB contract mismatch')
  if(m.android) inspectAndroid(root,m.android,previousApk)
  if(production) {
    const proof=await signingPlan()
    for(const row of proof.previous) {
      const current=verifySignedRelease(JSON.parse(fs.readFileSync(path.join(root,row.target,'release.json'))),{trust,profile:getTarget(row.target),currentVersion:'0.4.4'})
      if(current.sequence<proof.sequence || compareSemver(current.desktop.minimumVersion,row.minimum_version)<0) throw Error('Signed sequence/minimum rollback')
    }
  }
  return {schema:1,source_commit:m.source_commit,schema_head:contract.schema_head,production_ready:production,
    pending:production?[]:['formal-windows-envelopes','formal-android-apk','human-pg17-restore-and-device-acceptance'],targets:targetIds}
}
async function collect(root,zip,commit,androidPath,previousApk) {
  const targets=await collectWindows(root), contract=await readSourceArchive(zip,commit)
  const copy=async input => {
    const name=path.basename(input), destination=path.join(root,name)
    if(path.resolve(input)!==path.resolve(destination)) fs.copyFileSync(input,destination,fs.constants.COPYFILE_EXCL)
    const record=await fileRecord(root,name);return {file:name,size:record.size,sha256:record.sha256}
  }
  const manifest={schema:1,mode:'candidate',source_commit:commit,build_id:targets[0].build_id,
    trust_key_id:trust.keyId,desktop_version:'0.4.4',android_version:'1.2.3',android_version_code:10,
    targets,source_web:await copy(zip),source_contract:contract,android:null}
  if(androidPath) {
    if(path.basename(androidPath)!=='xiquan-mobile-ordering-1.2.3.apk') throw Error('Formal Android filename mismatch')
    manifest.android={...await copy(androidPath),...originalAndroid}
    inspectAndroid(root,manifest.android,previousApk)
  }
  await validateManifest(root,manifest,{previousApk})
  fs.writeFileSync(path.join(root,'stock-manifest.json'),JSON.stringify(manifest,null,2),{flag:'wx'})
  return manifest
}
async function finalize(root,apk,previousApk) {
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'stock-manifest.json')))
  const name='xiquan-mobile-ordering-1.2.3.apk'
  if(path.basename(apk)!==name) throw Error('Formal APK filename mismatch')
  const destination=path.join(root,name)
  if(path.resolve(apk)!==path.resolve(destination)) fs.copyFileSync(apk,destination,fs.constants.COPYFILE_EXCL)
  const record=await fileRecord(root,name)
  manifest.android={file:name,size:record.size,sha256:record.sha256,...originalAndroid}
  manifest.mode='production'
  await validateManifest(root,manifest,{production:true,previousApk})
  const manifestPath=path.join(root,'stock-manifest.json')
  fs.copyFileSync(manifestPath,path.join(root,`stock-manifest-candidate-${Date.now()}.json`),fs.constants.COPYFILE_EXCL)
  fs.writeFileSync(manifestPath,JSON.stringify(manifest,null,2))
  return {mode:'production',production_ready:true}
}
async function deliver(root,output,previousApk) {
  const manifest=JSON.parse(fs.readFileSync(path.join(root,'stock-manifest.json')))
  await validateManifest(root,manifest,{production:manifest.mode==='production',previousApk})
  if(fs.existsSync(output)) throw Error('Delivery directory exists; use a new exact directory, never overwrite')
  for(let current=path.resolve(output);;current=path.dirname(current)) {
    if(fs.existsSync(current) && fs.lstatSync(current).isSymbolicLink()) throw Error('Linked delivery ancestor forbidden')
    if(path.dirname(current)===current) break
  }
  fs.mkdirSync(output,{recursive:true})
  const records=[...manifest.targets.flatMap(r=>[r,r.blockmap,r.updater_manifest]),manifest.source_web]
  if(manifest.android) records.push(manifest.android)
  if(manifest.mode==='production') for(const id of targetIds) {
    const record=await fileRecord(root,`${id}/release.json`);records.push({file:record.fileName,size:record.size,sha256:record.sha256})
  }
  for(const name of ['delivery-index.json','stock-manifest.json']) {
    const row=await fileRecord(root,name);records.push({file:name,size:row.size,sha256:row.sha256})
  }
  for(const row of records) {
    const source=checkedFile(root,row,new Set()),destination=path.join(output,row.file)
    fs.mkdirSync(path.dirname(destination),{recursive:true});fs.copyFileSync(source,destination,fs.constants.COPYFILE_EXCL)
    checkedFile(output,row,new Set())
  }
  fs.writeFileSync(path.join(output,'SHA256SUMS'),records.map(r=>`${r.sha256}  ${r.file}`).join('\n')+'\n',{flag:'wx'})
  fs.writeFileSync(path.join(output,'PENDING.txt'),(manifest.mode==='candidate'?'CANDIDATE: formal APK and original-trust Windows update envelopes pending. ':'Signatures verified; ')+'PG17 restore, real Windows/Android/USB-printer acceptance and human publication pending. Win7 SP1/Electron22 is legacy unsupported; Win11 x86 is a 32-bit app on 64-bit Windows. Re-login cashier/inventory after upgrade.\n',{flag:'wx'})
  return {output,production_ready:manifest.mode==='production'}
}
module.exports={validateIdentity,validateAndroid,collectWindows,signingPlan,validateManifest,collect,deliver}
if(require.main===module) (async()=>{
  const [command,root,arg,commit,apk,previous]=process.argv.slice(2)
  if(command==='signing-plan') return signingPlan()
  if(command==='collect') return collect(root,arg,commit,apk,previous)
  if(command==='deliver') return deliver(root,arg,commit)
  if(command==='finalize') return finalize(root,arg,commit)
  if(command==='validate') return validateManifest(root,JSON.parse(fs.readFileSync(path.join(root,'stock-manifest.json'))),{production:arg==='production',previousApk:commit})
  throw Error('Usage: stock-release.cjs signing-plan | collect ROOT ZIP COMMIT [APK PREVIOUS] | deliver ROOT OUTPUT | validate ROOT [production PREVIOUS_APK]')
})().then(result=>console.log(JSON.stringify(result))).catch(error=>{console.error(error.message);process.exitCode=1})
