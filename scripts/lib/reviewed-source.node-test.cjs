const test=require('node:test'),assert=require('node:assert/strict')
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{spawnSync}=require('node:child_process')
const {assertReviewedSource}=require('./reviewed-source.cjs')
function fixture(){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'xiquan-reviewed-source-'))
  const git=args=>{const r=spawnSync('git',args,{cwd:root,encoding:'utf8',windowsHide:true});assert.equal(r.status,0,r.stderr);return r.stdout.trim()}
  fs.mkdirSync(path.join(root,'mobile/public'),{recursive:true});fs.mkdirSync(path.join(root,'mobile/src'))
  fs.writeFileSync(path.join(root,'mobile/version.json'),JSON.stringify({version:'1.2.4',versionCode:11,minimumVersionCode:9}))
  fs.writeFileSync(path.join(root,'mobile/public/download-config.json'),'{}')
  fs.writeFileSync(path.join(root,'mobile/src/app.ts'),'export const production=true')
  git(['init']);git(['add','.']);git(['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture'])
  return {root,commit:git(['rev-parse','HEAD']),close:()=>fs.rmSync(root,{recursive:true,force:true})}
}
test('reviewed source rejects edits and wrong HEAD but permits only generated config and version formatting',()=>{
  const f=fixture()
  try{
    assertReviewedSource(f.root,f.commit)
    fs.writeFileSync(path.join(f.root,'mobile/public/download-config.json'),'{}\n')
    assertReviewedSource(f.root,f.commit)
    assert.throws(()=>assertReviewedSource(f.root,'a'.repeat(40)))
    fs.writeFileSync(path.join(f.root,'mobile/src/app.ts'),'export const production=false')
    assert.throws(()=>assertReviewedSource(f.root,f.commit))
  }finally{f.close()}
})
test('post-build check rejects version changes, accepts equivalent JSON formatting only',()=>{
  const f=fixture()
  try{
    fs.writeFileSync(path.join(f.root,'mobile/version.json'),'\ufeff{\n "version":"1.2.4", "versionCode":11, "minimumVersionCode":9\n}\n')
    assertReviewedSource(f.root,f.commit,{afterAndroidBuild:true})
    fs.writeFileSync(path.join(f.root,'mobile/version.json'),JSON.stringify({version:'1.2.4',versionCode:12,minimumVersionCode:9}))
    assert.throws(()=>assertReviewedSource(f.root,f.commit,{afterAndroidBuild:true}))
  }finally{f.close()}
})
