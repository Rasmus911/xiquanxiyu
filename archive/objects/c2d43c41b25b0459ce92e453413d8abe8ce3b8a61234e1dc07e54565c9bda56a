[CmdletBinding()]
param([string]$PrivateKeyPath='F:\溪泉洗浴系统\private\溪泉发布密钥\desktop-release-private.pem',[string]$Job,[string]$EcsTarget='root@39.96.217.210')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$delivery=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8 | ConvertFrom-Json
& node.exe (Join-Path $delivery.ProjectRoot 'scripts\lib\reviewed-source.cjs') $delivery.ProjectRoot $delivery.SourceCommit
if($LASTEXITCODE-ne 0){throw 'Frozen source differs; no signing or upload.'}
if($EcsTarget-notmatch '^[A-Za-z0-9_-]+@[A-Za-z0-9.-]+$'){throw 'Invalid SSH target'}
if(-not $Job){
    $resultPath=Join-Path $PSScriptRoot '云端部署结果.json'
    if(Test-Path -LiteralPath $resultPath){$Job=(Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8|ConvertFrom-Json).Job}
}
if($Job-notmatch '^/opt/xiquan-backups/desktop050-cutover-[0-9a-f]{32}$'){throw 'Run 01 successfully first, or supply its exact -Job checkpoint.'}
if((Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $delivery.SourceZipFile) -Algorithm SHA256).Hash.ToLowerInvariant()-cne $delivery.SourceSha256){throw 'Delivered source hash changed'}
. (Join-Path $delivery.ProjectRoot 'scripts\lib\mobile-128-transport.ps1')
$check=@"
import json, subprocess
from pathlib import Path
p=Path('$Job')
if any(v.is_symlink() for v in (p,*p.parents)): raise SystemExit('CHECKPOINT_PATH_INVALID')
r=json.loads((p/'completed.json').read_text())
assert r['source_commit']=='$($delivery.SourceCommit)' and r['source_sha256']=='$($delivery.SourceSha256)'
assert r['schema']=='20261011_service_receipts' and r['desktop_version']=='0.5.0' and r['receipt_cleanup'] is True
api=json.loads(subprocess.check_output(['docker','inspect','xiquan-api-1'],text=True))[0]
assert api['Image']==r['image_id'] and api['State']['Running'] and api['State']['Health']['Status']=='healthy'
worker=json.loads(subprocess.check_output(['docker','inspect','xiquan-receipt-cleanup-1'],text=True))[0]
assert worker['Image']==r['image_id'] and worker['State']['Running'] and worker['State']['Health']['Status']=='healthy'
print(json.dumps({'completed':True,'source_commit':r['source_commit'],'schema':r['schema']}))
"@
$checked=Invoke-TokenNative -Executable 'ssh.exe' -Arguments @('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3',$EcsTarget,'python3 -') -InputText ($check-replace "`r",'') -TimeoutSeconds 90 -Label 'VERIFY EXACT CLOUD COMPLETED'
if($checked.ExitCode-ne 0){throw 'Cloud completed/image/health evidence failed. No signing/upload.'}
$receipt=$checked.Stdout|ConvertFrom-Json
if(-not $receipt.completed -or $receipt.source_commit-cne $delivery.SourceCommit){throw 'Cloud receipt differs'}
$confirmation=Read-Host 'Cloud receipt verified. Type PUBLISH 0.5.0'
if($confirmation-cne 'PUBLISH 0.5.0'){throw 'Cancelled; nothing signed/uploaded'}
& (Join-Path $delivery.ProjectRoot 'scripts\sign-desktop-050.ps1') -ReleaseRoot $delivery.ReleaseRoot -PrivateKeyPath $PrivateKeyPath
& (Join-Path $delivery.ProjectRoot 'scripts\publish-windows-release.ps1') -ReleaseRoot $delivery.ReleaseRoot -EcsTarget $EcsTarget -Targets @('win10-x86','win10-x64','win11-x86','win11-x64')
Write-Host 'Four signed channels published and publicly verified. Old clients can check updates at login.'
