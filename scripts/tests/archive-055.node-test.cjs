const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const file=path.join(__dirname,'../archive-desktop-055.cjs'),archive=fs.existsSync(file)?require(file):{}
test('055 archive accepts the exact old delivery and derived tree, never latest or signing references',()=>{
  assert.equal(typeof archive.versionFor,'function')
  assert.equal(archive.versionFor('最新版安装包-刷卡开牌-0.5.4/Xiquan-Bathhouse-Setup-0.5.4-win10-x64.exe'),'0.5.4')
  assert.equal(archive.versionFor('release/windows/0.5.4/build/win11-x86/installer.exe'),'0.5.4')
  assert.equal(archive.versionFor('release/cloud/xiquan-desktop054-SOURCE-WEB-20261013-115235-9bf0698f.zip'),'0.5.4')
  for(const name of ['最新版安装包-人工库存与Excel-0.5.5/app.exe','release/windows/0.5.5/current.exe',
    'release/mobile/xiquan-mobile-ordering-1.2.11.apk','private/desktop055/key.pem',
    'release/windows/0.5.4/build/private.pem','release/windows/0.5.4/build/.env','release/windows/0.5.4/../0.5.5/app.exe']){
    assert.throws(()=>archive.versionFor(name))
  }
  assert.equal(archive.category('old.exe','0.5.4'),'desktop/0.5.4/shared')
})
test('055 cleanup only accepts fresh exact remote identities for the reviewed old files',()=>{
  assert.equal(typeof archive.validateCleanup,'function')
  const entry={path:'release/windows/0.5.4/build/win10-x64/app.exe',version:'0.5.4',size:12,sha256:'a'.repeat(64),pieces:[{file:'archive/objects/'+'a'.repeat(64),size:12,sha256:'a'.repeat(64)}]}
  const proof={repository:'https://github.com/Rasmus911/xiquanxiyu',remoteCommit:'b'.repeat(40),verifiedAt:'2026-10-13T10:00:00Z',entries:[entry]}
  const now=new Date('2026-10-13T11:00:00Z')
  assert.equal(archive.validateCleanup(entry,proof,now),true)
  assert.throws(()=>archive.validateCleanup({...entry,path:'release/windows/0.5.5/new.exe'},proof,now))
  assert.throws(()=>archive.validateCleanup({...entry,sha256:'c'.repeat(64)},proof,now))
  assert.throws(()=>archive.validateCleanup(entry,{...proof,repository:'https://github.com/else/else'},now))
  assert.throws(()=>archive.validateCleanup(entry,proof,new Date('2026-10-15T11:00:00Z')))
})
