const fs=require('node:fs'),path=require('node:path')
const base=require('./desktop-045.cjs')
const {trust:originalTrust,checkedFile}=require('./operations-release.cjs')
const {verifyReleaseSet}=require('./desktop-release.cjs')
const {verifySignedRelease}=require('../../client/electron/desktop-release.cjs')
const releaseVersion='0.5.5'
const releaseNotes=Object.freeze(['取消下单“选择耗材”的步骤','可以通过导入外部Excel来整理库存'])
const targets=base.targets
function verifiedHistory(history,trust){
  if(!Array.isArray(history)||history.length>10000)throw Error('Invalid signed history')
  return history.map(row=>{
    if(!targets.includes(row.target))throw Error('Unknown history target')
    const signed=verifySignedRelease(row.envelope,{trust,profile:require('../../client/electron/target-profiles.cjs').getTarget(row.target),currentVersion:'0.0.0'})
    return {target:row.target,sequence:signed.sequence,envelope:row.envelope}
  })
}
function readLocalHistory(project){
  const root=path.join(project,'release','windows'),history=[]
  if(!fs.existsSync(root))return history
  // Inspect only explicit release/version/build/target manifests, never private keys or arbitrary files.
  for(const version of fs.readdirSync(root,{withFileTypes:true})){
    if(!version.isDirectory()||!/^\d+\.\d+\.\d+$/.test(version.name)||version.name===releaseVersion||version.isSymbolicLink())continue
    for(const build of fs.readdirSync(path.join(root,version.name),{withFileTypes:true})){
      if(!build.isDirectory()||build.isSymbolicLink())continue
      for(const target of targets){
        const file=path.join(root,version.name,build.name,target,'release.json')
        if(!fs.existsSync(file))continue
        const stat=fs.lstatSync(file)
        if(!stat.isFile()||stat.isSymbolicLink()||stat.size>128*1024)throw Error('Unsafe signed history file')
        history.push({target,envelope:JSON.parse(fs.readFileSync(file,'utf8').replace(/^\ufeff/,''))})
      }
    }
  }
  return history
}
async function signingPlan({history=[],trust=originalTrust,...options}={}){
  const plan=await base.signingPlan({...options,trust,version:releaseVersion})
  const retained=verifiedHistory(history,trust)
  const sequence=Math.max(...plan.previous.map(row=>row.sequence),...retained.map(row=>row.sequence))+1
  if(!Number.isSafeInteger(sequence)||sequence>2147483647)throw Error('Release sequence exhausted')
  return {...plan,sequence,history:retained}
}
function validatePlan(plan,{trust=originalTrust}={}){
  if(plan.version!==releaseVersion||plan.trust_key_id!==trust.keyId||JSON.stringify(plan.previous?.map(row=>row.target))!==JSON.stringify(targets))throw Error('Verified plan identity invalid')
  const previous=verifiedHistory(plan.previous,trust),history=verifiedHistory(plan.history,trust)
  for(let i=0;i<previous.length;i++){
    if(plan.previous[i].sequence!==previous[i].sequence)throw Error('Previous sequence changed')
    const signed=verifySignedRelease(plan.previous[i].envelope,{trust,profile:require('../../client/electron/target-profiles.cjs').getTarget(previous[i].target),currentVersion:'0.0.0'})
    if(plan.previous[i].minimum_version!==signed.desktop.minimumVersion)throw Error('Previous minimum changed')
  }
  if(plan.sequence!==Math.max(...previous.map(row=>row.sequence),...history.map(row=>row.sequence))+1)throw Error('Verified signing sequence invalid')
  return true
}
async function inspectPublication(root,{trust=originalTrust}={}){
  const index=await verifyReleaseSet(root,targets,{mode:'candidate',trust})
  if(index.version!==releaseVersion)throw Error('Expected desktop version 0.5.5')
  const signatures=[]
  for(const target of targets){
    const file=path.join(root,target,'release.json');if(!fs.existsSync(file))continue
    await verifyReleaseSet(root,[target],{mode:'release',trust})
    const signed=verifySignedRelease(JSON.parse(fs.readFileSync(file,'utf8')),{trust,profile:index.targets.find(row=>row.profile.targetId===target).profile,currentVersion:releaseVersion})
    if(JSON.stringify(signed.desktop.releaseNotes)!==JSON.stringify(releaseNotes))throw Error('Signed release notes differ')
    signatures.push({target,sequence:signed.sequence,minimumVersion:signed.desktop.minimumVersion})
  }
  if(new Set(signatures.map(row=>row.sequence)).size>1)throw Error('Signed sequence differs across targets')
  return {version:index.version,buildId:index.buildId,targets,signedTargets:signatures.map(row=>row.target),unsignedTargets:targets.filter(id=>!signatures.some(row=>row.target===id)),signatures}
}
async function remainingSigningGroups(root,plan,{trust=originalTrust}={}){
  validatePlan(plan,{trust})
  const state=await inspectPublication(root,{trust})
  for(const signed of state.signatures){
    if(signed.sequence!==plan.sequence||signed.minimumVersion!==plan.previous.find(row=>row.target===signed.target).minimum_version)throw Error('Existing signature differs; no overwrite')
  }
  const groups=[]
  for(const row of plan.previous){
    if(!state.unsignedTargets.includes(row.target))continue
    let group=groups.find(value=>value.minimumVersion===row.minimum_version)
    if(!group){group={minimumVersion:row.minimum_version,targets:[]};groups.push(group)}
    group.targets.push(row.target)
  }
  return groups
}
async function verifyDelivery(root){
  const delivery=JSON.parse(fs.readFileSync(path.join(root,'交付信息.json'),'utf8').replace(/^\ufeff/,''))
  if(delivery.Version!==releaseVersion||JSON.stringify(delivery.Targets)!==JSON.stringify(targets)||!path.isAbsolute(delivery.ReleaseRoot)||!path.isAbsolute(delivery.ProjectRoot))throw Error('Delivery identity invalid')
  if(!Array.isArray(delivery.Files)||!Array.isArray(delivery.ProjectFiles))throw Error('Delivery file manifest missing')
  const deliverySeen=new Set();for(const record of delivery.Files)checkedFile(root,record,deliverySeen)
  const seen=new Set();for(const record of delivery.ProjectFiles)checkedFile(delivery.ProjectRoot,record,seen)
  const state=await inspectPublication(delivery.ReleaseRoot)
  if(state.buildId!==delivery.BuildId)throw Error('Delivery build identity differs')
  const index=await verifyReleaseSet(delivery.ReleaseRoot,targets,{mode:'candidate',trust:originalTrust})
  for(const row of index.targets){
    const delivered=delivery.Files.find(record=>record.file===row.artifact.fileName)
    if(!delivered||delivered.sha256!==row.artifact.sha256||delivered.size!==row.artifact.size)throw Error('Delivery installer differs')
  }
  return {verified:true,version:state.version,buildId:state.buildId,signedTargets:state.signedTargets,unsignedTargets:state.unsignedTargets}
}
module.exports={releaseVersion,releaseNotes,targets,signingPlan,validatePlan,readLocalHistory,inspectPublication,remainingSigningGroups,verifyDelivery}
if(require.main===module)(async()=>{
  const [mode,root]=process.argv.slice(2)
  if(mode==='plan'){
    const history=readLocalHistory(path.resolve(__dirname,'../..'))
    if(root)history.push(...JSON.parse(fs.readFileSync(path.join(root,'historical-signed-releases.json'),'utf8')))
    return signingPlan({history})
  }
  if(mode==='history')return verifiedHistory(readLocalHistory(path.resolve(__dirname,'../..')),originalTrust).map(({target,sequence})=>({target,sequence}))
  if(mode==='retained-history'){
    const history=readLocalHistory(root)
    for(const folder of fs.readdirSync(root,{withFileTypes:true})){
      if(!folder.isDirectory()||folder.isSymbolicLink()||!folder.name.startsWith('最新版安装包-'))continue
      const file=path.join(root,folder.name,'historical-signed-releases.json')
      if(fs.existsSync(file)){
        const stat=fs.lstatSync(file)
        if(!stat.isFile()||stat.isSymbolicLink()||stat.size>16*1024*1024)throw Error('Unsafe historical signature file')
        history.push(...JSON.parse(fs.readFileSync(file,'utf8').replace(/^\ufeff/,'')))
      }
    }
    return verifiedHistory(history,originalTrust)
  }
  if(mode==='status')return inspectPublication(root)
  if(mode==='verify-delivery')return verifyDelivery(root)
  if(mode==='groups'){let text='';for await(const chunk of process.stdin)text+=chunk;return remainingSigningGroups(root,JSON.parse(text.replace(/^\ufeff/,'')))}
  throw Error('Unknown desktop055 operation')
})().then(value=>console.log(JSON.stringify(value))).catch(error=>{console.error(error.message);process.exitCode=1})
