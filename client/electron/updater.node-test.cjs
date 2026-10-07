const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const vm = require('node:vm')
const crypto = require('node:crypto')
const {EventEmitter}=require('node:events')
const {getTarget}=require('./target-profiles.cjs')

function loadAdapter({testOnly=false,packaged=true,metadataMissing=false,target='win7-x86',currentVersion='0.4.2',latestVersion='0.4.3'}={}) {
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'xiquan-updater-adapter-'))
  const {publicKey,privateKey}=crypto.generateKeyPairSync('ed25519')
  const publicKeyPem=publicKey.export({type:'spki',format:'pem'})
  const keyId=crypto.createHash('sha256').update(publicKey.export({type:'spki',format:'der'})).digest('hex').slice(0,16)
  const profile=getTarget(target),body=Buffer.from('release-bytes'),yaml=Buffer.from(`version: ${latestVersion}\n`)
  const artifact={fileName:`Xiquan-Bathhouse-Setup-${latestVersion}-${target}.exe`,size:body.length,
    sha256:crypto.createHash('sha256').update(body).digest('hex'),sha512:crypto.createHash('sha512').update(body).digest('base64')}
  const payload={schemaVersion:2,keyId,sequence:1,buildId:'adapter-fixture',...profile,
    desktop:{latestVersion,minimumVersion:'0.4.2',required:false,releaseNotes:[],publishedAt:'2026-10-03T00:00:00Z',
      downloadUrl:`https://api.pqxqxy.xyz/updates/desktop/${target}/${artifact.fileName}`,sha256:artifact.sha256},artifact,
    blockmap:{fileName:artifact.fileName+'.blockmap',size:2,sha256:'b'.repeat(64)},
    updaterManifest:{fileName:'latest.yml',sha256:crypto.createHash('sha256').update(yaml).digest('hex')}}
  const bytes=Buffer.from(JSON.stringify(payload)),envelope={payload:bytes.toString('base64'),signature:crypto.sign(null,bytes,privateKey).toString('base64')}
  const calls=[]
  const updater=new EventEmitter()
  updater.setFeedURL=value=>calls.push(value.url)
  updater.checkForUpdates=async()=>({updateInfo:{version:latestVersion,files:[{url:artifact.fileName,size:artifact.size,sha512:artifact.sha512}],path:artifact.fileName,sha512:artifact.sha512}})
  const downloaded=path.join(directory,'candidate.exe'); fs.writeFileSync(downloaded,body)
  updater.downloadUpdate=async()=>[downloaded]; updater.quitAndInstall=()=>{}
  const app={isPackaged:packaged,getVersion:()=>currentVersion,getPath:()=>directory}
  const context={module:{exports:{}},exports:{},__dirname:path.join(__dirname),Buffer,URL,console,
    process:{platform:'win32',arch:profile.arch,versions:{electron:profile.electronVersion}},
    setTimeout:()=>({unref(){}}),setInterval:()=>({unref(){}}),clearTimeout(){},clearInterval(){},setImmediate,
    require:name=>{
      if(name==='electron')return {app,Notification:{isSupported:()=>false}}
      if(name==='electron-updater')return {autoUpdater:updater}
      if(name==='electron-updater/out/electronHttpExecutor')return {ElectronHttpExecutor:class{}}
      if(name==='node:os')return {release:()=>target.startsWith('win7')?'6.1.7601':target.startsWith('win11')?'10.0.22631':'10.0.19045'}
      if(name==='../package.json')return {version:currentVersion,xiquanDesktop:metadataMissing?undefined:{schemaVersion:1,...profile,buildId:'adapter-fixture',releaseTrust:{keyId,publicKeyPem,testOnly}}}
      if(name==='./https-json.cjs')return {
        requestHttpsJson:async url=>{calls.push(String(url));return envelope},
        requestHttpsBuffer:async url=>{calls.push(String(url));return yaml},
      }
      return require(name)
    }}
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'updater.cjs'),'utf8'),context,{filename:'updater.cjs'})
  return {adapter:context.module.exports,calls,updater,directory,close:()=>fs.rmSync(directory,{recursive:true,force:true})}
}

test('the real adapter selects the packaged channel, verifies bytes and ignores mutable server update origins',async()=>{
  const f=loadAdapter()
  try {
    f.adapter.start('https://evil.invalid/api',()=>null)
    await f.adapter.checkForUpdates()
    assert.equal(f.adapter.getState().status,'downloaded')
    assert.equal(f.adapter.getTargetIdentity().targetId,'win7-x86')
    assert.equal(f.calls.includes('https://api.pqxqxy.xyz/updates/desktop/win7-x86/'),true)
    assert.equal(f.calls.some(value=>value.includes('evil.invalid')),false)
    assert.equal(f.updater.autoInstallOnAppQuit,false)
    assert.equal(fs.existsSync(path.join(f.directory,'desktop-update-state-win7-x86.json')),true)
  } finally {f.close()}
})

test('test-only and development packages make no update requests',async()=>{
  for(const options of [{testOnly:true},{packaged:false}]) {
    const f=loadAdapter(options)
    try {f.adapter.start('',()=>null);await f.adapter.checkForUpdates();assert.equal(f.adapter.getState().status,'disabled');assert.deepEqual(f.calls,[])}
    finally {f.close()}
  }
})

test('missing packaged identity produces an actionable error without global-feed fallback',async()=>{
  const f=loadAdapter({metadataMissing:true})
  try {await f.adapter.checkForUpdates();assert.equal(f.adapter.getState().status,'error');assert.equal(Boolean(f.adapter.getStartupError()),true);assert.deepEqual(f.calls,[])}
  finally {f.close()}
})

test('0.4.4 through 0.4.7 verify and download 0.4.8 through matching Win10/11 signed channels', async () => {
  for (const currentVersion of ['0.4.4','0.4.5','0.4.6','0.4.7']) {
    for (const target of ['win10-x86','win10-x64','win11-x86','win11-x64']) {
      const f = loadAdapter({ target, currentVersion, latestVersion:'0.4.8' })
      try {
        f.adapter.start('https://api.pqxqxy.xyz/api',()=>null)
        await f.adapter.checkForUpdates()
        assert.equal(f.adapter.getState().status,'downloaded', `${currentVersion}/${target}`)
        assert.equal(f.calls.includes(`https://api.pqxqxy.xyz/updates/desktop/${target}/`),true)
      } finally { f.close() }
    }
  }
})
