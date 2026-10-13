const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs')
const {makeWindowsConfig}=require('./windows-config.cjs')
const {testTrust}=require('./windows-pack.cjs')
test('all current Windows installers use the same packaged brand icon without changing upgrade identity',()=>{
 const root=path.resolve(__dirname,'../..'),trust=testTrust()
 for(const targetId of ['win10-x86','win10-x64','win11-x86','win11-x64']){
  const config=makeWindowsConfig({projectRoot:root,version:'0.5.6',buildId:'icon056-test',targetId,trust})
  assert.equal(config.win.icon,path.join(root,'client/electron/assets/xiquan.ico'))
  assert.equal(config.nsis.installerIcon,config.win.icon)
  assert.equal(config.nsis.uninstallerIcon,config.win.icon)
  assert.equal(config.appId,'com.xiquan.bathhouse')
 }
})
