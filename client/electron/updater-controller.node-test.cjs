const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { createUpdaterController } = require('./updater-controller.cjs')

function fixture() {
  const updater = new EventEmitter()
  const calls = { check:0, download:0, verify:0, install:0 }
  const immediate = []
  const artifact = { fileName:'Xiquan-Bathhouse-Setup-0.4.3-win7-x86.exe', size:17, sha512:'a'.repeat(86)+'==', sha256:'b'.repeat(64) }
  const release = { profile:{targetId:'win7-x86'}, artifact,
    desktop:{ latestVersion:'0.4.3',minimumVersion:'0.4.2',required:false,releaseNotes:['test'],downloadUrl:'https://api.pqxqxy.xyz/updates/desktop/win7-x86/a.exe' } }
  let load = async () => release
  let verify = async () => { calls.verify++ }
  updater.checkForUpdates = async () => { calls.check++; return {updateInfo:{version:'0.4.3',files:[{url:artifact.fileName,size:17,sha512:artifact.sha512}],path:artifact.fileName,sha512:artifact.sha512}} }
  updater.downloadUpdate = async () => { calls.download++; updater.emit('download-progress',{percent:100}); return ['candidate.exe'] }
  updater.quitAndInstall = () => { calls.install++ }
  const controller = createUpdaterController({ updater, app:{isPackaged:true,getVersion:()=>'0.4.2'},
    clock:{setImmediate:fn=>immediate.push(fn)}, loadRelease:()=>load(), verifyArtifact:(...args)=>verify(...args), emit:()=>{}, notify:()=>{} })
  return { controller, updater, calls, release, immediate,
    setLoad:fn=>{load=fn},setVerify:fn=>{verify=fn},flush:()=>{while(immediate.length)immediate.shift()()} }
}

test('signature failure never downloads or installs and exposes a sanitized error', async () => {
  const f=fixture(); f.setLoad(async()=>{throw Error('invalid signature 签名 https://u:p@host')})
  await f.controller.checkForUpdates()
  assert.equal(f.controller.getState().status,'error')
  assert.equal(f.controller.getState().message.includes('u:p'),false)
  assert.equal(f.calls.download,0)
  assert.equal(f.controller.installUpdate().ok,false)
})

test('metadata mismatches cannot reach download and corrupt bytes cannot reach installation', async () => {
  const f=fixture(); f.updater.checkForUpdates=async()=>({updateInfo:{version:'0.4.3',files:[{url:'wrong.exe'}]}})
  await f.controller.checkForUpdates(); assert.equal(f.calls.download,0); assert.equal(f.controller.getState().status,'error')
  const bad=fixture(); bad.setVerify(async()=>{throw Error('更新文件校验失败')})
  await bad.controller.checkForUpdates()
  assert.equal(bad.controller.getState().status,'error')
  assert.equal(bad.controller.installUpdate().ok,false); bad.flush(); assert.equal(bad.calls.install,0)
})

test('verified download can be installed only once and only while idle', async () => {
  const f=fixture(); await f.controller.checkForUpdates()
  assert.equal(f.controller.getState().status,'downloaded')
  assert.equal(f.calls.verify,1)
  f.controller.setBusinessBusy('正在完成会员充值')
  assert.equal(f.controller.installUpdate().ok,false)
  const event={prevented:false,preventDefault(){this.prevented=true}}
  f.controller.onBeforeQuit(event); assert.equal(event.prevented,true)
  f.controller.setBusinessBusy(null)
  assert.equal(f.controller.installUpdate().ok,true)
  assert.equal(f.controller.installUpdate().ok,false)
  f.flush(); assert.equal(f.calls.install,1)
})

test('busy state is checked again after the user clicks install', async () => {
  const f=fixture(); await f.controller.checkForUpdates()
  f.controller.installUpdate(); f.controller.setBusinessBusy('正在结账'); f.flush()
  assert.equal(f.calls.install,0)
  assert.equal(f.controller.getState().status,'downloaded')
})

test('normal exit never uses unchecked auto-install and an idle verified exit shares the install gate', async () => {
  const f=fixture()
  assert.equal(f.updater.autoDownload,false); assert.equal(f.updater.autoInstallOnAppQuit,false)
  const event={prevented:false,preventDefault(){this.prevented=true}}
  f.controller.onBeforeQuit(event); assert.equal(event.prevented,false)
  await f.controller.checkForUpdates(); f.controller.onBeforeQuit(event); assert.equal(event.prevented,true)
  f.flush(); assert.equal(f.calls.install,1)
  const installing={prevented:false,preventDefault(){this.prevented=true}}
  f.controller.onBeforeQuit(installing); assert.equal(installing.prevented,false)
})

test('simultaneous checks share one flight and a forced minimum is not lost on updater noise', async () => {
  const f=fixture(); let finish
  f.setLoad(()=>new Promise(resolve=>{finish=resolve}))
  const first=f.controller.checkForUpdates(); await Promise.resolve()
  await f.controller.checkForUpdates(); assert.equal(f.calls.check,0)
  finish({...f.release,desktop:{...f.release.desktop,minimumVersion:'0.4.3'}}); await first
  f.updater.emit('update-not-available',{version:'0.4.2'})
  assert.equal(f.controller.getState().required,true)
  assert.equal(f.calls.check,1)
})

test('an updater error invalidates previously downloaded installation eligibility', async () => {
  const f=fixture(); await f.controller.checkForUpdates()
  f.updater.emit('error',Error('network token secret'))
  assert.equal(f.controller.installUpdate().ok,false)
  assert.equal(f.controller.getState().message.includes('secret'),false)
})
