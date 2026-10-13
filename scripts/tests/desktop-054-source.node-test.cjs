const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{spawnSync}=require('node:child_process')
test('Android build retains exact frozen version bytes when release identity is unchanged',t=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'xiquan-version-contract-'))
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}))
  const file=path.join(root,'version.json'),original='{"version":"1.2.11","versionCode":18,"minimumVersionCode":9}\n'
  fs.writeFileSync(file,original)
  const source=fs.readFileSync(path.join(__dirname,'../build-mobile-release.ps1'),'utf8')
  const block=source.slice(source.indexOf('$versionConfig ='),source.indexOf('$storeSecure ='))
  const program=`$ErrorActionPreference='Stop'\n$Version='1.2.11';$VersionCode=18;$MinimumVersionCode=9\n$versionPath='${file.replace(/'/g,"''")}'\nfunction Write-Utf8Json($Path,$Value){[IO.File]::WriteAllText($Path,($Value|ConvertTo-Json -Depth 8)+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))}\n${block}\n`
  const run=spawnSync('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-Command','-'],{input:program,encoding:'utf8',windowsHide:true})
  assert.equal(run.status,0,run.stderr)
  assert.equal(fs.readFileSync(file,'utf8'),original)
})
