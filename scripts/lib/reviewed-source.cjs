const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process')
function assertReviewedSource(root,commit,{afterAndroidBuild=false}={}){
  if(!/^[0-9a-f]{40}$/.test(commit))throw Error('Reviewed source commit required')
  function git(args){const result=spawnSync('git',args,{cwd:root,encoding:'utf8',windowsHide:true});if(result.status!==0)throw Error('Reviewed source changed or unavailable');return result.stdout}
  if(git(['rev-parse','HEAD']).trim()!==commit)throw Error('HEAD differs from delivered source')
  const args=['diff','--quiet','HEAD','--','.',':(exclude)mobile/public/download-config.json']
  if(afterAndroidBuild){
    args.push(':(exclude)mobile/version.json')
    const before=JSON.parse(git(['show',commit+':mobile/version.json']).replace(/^\ufeff/,''))
    const after=JSON.parse(fs.readFileSync(path.join(root,'mobile/version.json'),'utf8').replace(/^\ufeff/,''))
    const normalized=value=>JSON.stringify(Object.keys(value).sort().map(key=>[key,value[key]]))
    if(normalized(before)!==normalized(after))throw Error('Android source version changed during build')
  }
  git(args)
  return {sourceCommit:commit,reviewed:true}
}
module.exports={assertReviewedSource}
if(require.main===module){try{console.log(JSON.stringify(assertReviewedSource(process.argv[2],process.argv[3],{afterAndroidBuild:process.argv[4]==='after-android'})))}catch(error){console.error(error.message);process.exitCode=1}}
