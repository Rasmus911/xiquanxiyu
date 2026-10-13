const test=require('node:test'),assert=require('node:assert/strict'),{versionFor,category}=require('../archive-desktop-054.cjs')
test('archive054 accepts exact historical 053 artifacts, never latest or private files',()=>{
  assert.equal(versionFor('最新版安装包-暖木泉境-0.5.3/release-public-key.pem'),'0.5.3')
  assert.equal(versionFor('release/windows/0.5.3/build/win10-x86/installer.exe'),'0.5.3')
  for(const file of ['最新版安装包-刷卡开牌-0.5.4/app.exe','private/key.pem','release/windows/0.5.3/private/key.pem','release/windows/0.5.3/build/private.pem'])assert.throws(()=>versionFor(file))
  assert.equal(category('app.apk','1.2.10'),'mobile/1.2.10')
})
