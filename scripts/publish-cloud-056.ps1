[CmdletBinding()]
param([Parameter(Mandatory)][string]$DeliveryRoot,[string]$EcsTarget='root@39.96.217.210',[switch]$ValidateOnly,[switch]$VerifyOnly)
$ErrorActionPreference='Stop'
$project=Split-Path -Parent $PSScriptRoot
$delivery=(Resolve-Path -LiteralPath $DeliveryRoot).Path
$info=Get-Content -LiteralPath (Join-Path $delivery '交付信息.json') -Raw -Encoding UTF8|ConvertFrom-Json
& node.exe (Join-Path $PSScriptRoot 'lib\desktop-056.cjs') verify-delivery $delivery
if($LASTEXITCODE-ne 0){throw 'Delivery differs; no SSH or restart.'}
if($ValidateOnly){Write-Host 'LOCAL056_VALIDATED: no connection, signing or migration.';return}
if($VerifyOnly){
 & node.exe (Join-Path $PSScriptRoot 'lib\static-056-public.cjs') $delivery
 if($LASTEXITCODE-ne 0){throw 'Read-only public verification incomplete; keep publication evidence.'}
 $receiptFile=Join-Path $project 'private\desktop056\completed.json'
 $receipt=Get-Content -LiteralPath $receiptFile -Raw -Encoding UTF8|ConvertFrom-Json
 if($receipt.source_commit-cne $info.SourceCommit-or $receipt.api_sha256-cne $info.ApiSha256-or $receipt.web_sha256-cne $info.WebSha256){throw 'Saved completion receipt differs'}
 $receipt.public_verified=$true
 [IO.File]::WriteAllText($receiptFile,($receipt|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false));return
}
if($EcsTarget-notmatch '^[A-Za-z0-9_-]+@[A-Za-z0-9.-]+$'){throw 'Invalid SSH target'}
if((Read-Host 'Only inventory export code and web files change; no migration. Type PUBLISH CLOUD 0.5.6')-cne 'PUBLISH CLOUD 0.5.6'){throw 'Cancelled'}
. (Join-Path $PSScriptRoot 'lib\desktop-053-transport.ps1')
$options=@('-T','-o','ConnectTimeout=20','-o','ConnectionAttempts=1','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
$remote='/tmp/xiquan-token128-'+[guid]::NewGuid().ToString('N')
function Remote([string]$command,[int]$seconds=180){
 $result=Invoke-TokenNative -Executable 'ssh.exe' -Arguments ($options+@($EcsTarget,$command)) -TimeoutSeconds $seconds -Label 'DESKTOP056 cloud publication'
 Write-Host $result.Stdout
 if($result.ExitCode-ne 0){Write-Host $result.Stderr;throw ('Cloud step stopped. Keep evidence and transport: '+$remote+'; no database restore.')}
 return $result.Stdout
}
$null=Remote ('umask 077 && mkdir -m 700 '+$remote) 45
function Upload([string]$local,[string]$name){
 Write-Host ('UPLOAD_AND_SHA256: '+$name)
 $program=New-TokenUploadProgram -LocalPath $local -RemotePath ($remote+'/'+$name)
 $result=Invoke-TokenNative -Executable 'ssh.exe' -Arguments ($options+@($EcsTarget,'python3 -')) -InputText ($program+"`n") -TimeoutSeconds 600 -Label ('DESKTOP056 '+$name)
 $hash=(Get-FileHash -LiteralPath $local -Algorithm SHA256).Hash.ToLowerInvariant()
 if($result.ExitCode-ne 0-or $result.Stdout-notmatch ('(?m)^UPLOAD_VERIFIED '+$hash+' '+[regex]::Escape($remote+'/'+$name)+'\r?$')){throw ('Upload hash not verified; keep '+$remote)}
 Write-Host ('FILE_VERIFIED: '+$name)
}
Upload (Join-Path $project 'deploy\cloud\scripts\desktop056_format_patch.py') 'patch.py'
Upload (Join-Path $delivery 'inventory_xlsx.py') 'inventory_xlsx.py'
Upload (Join-Path $project 'deploy\cloud\scripts\static056_publication.py') 'static.py'
Upload (Join-Path $delivery 'web-0.5.6.zip') 'web.zip'
$patchOutput=Remote ('python3 -u '+$remote+'/patch.py --source '+$remote+'/inventory_xlsx.py --sha256 '+$info.ApiSha256) 360
$match=[regex]::Match($patchOutput,'PRIVATE_DESKTOP056_PATCH_JOB=(/opt/xiquan-backups/desktop056-format-[a-f0-9]{32})')
if(-not $match.Success){throw 'API patch receipt identity not printed; stop, no guessed completion.'}
$patch=(Remote ('cat '+$match.Groups[1].Value+'/completed.json') 60)|ConvertFrom-Json
if($patch.source_sha256-cne $info.ApiSha256-or $patch.new_image-notmatch '^sha256:[a-f0-9]{64}$'){throw 'API completion receipt differs'}
$webOutput=Remote ('python3 -u '+$remote+'/static.py --archive '+$remote+'/web.zip --sha256 '+$info.WebSha256+' --commit '+$info.SourceCommit) 180
if($webOutput-notmatch 'STATIC056_RECEIPT='){throw 'Static completion evidence missing'}
$completed=@{version='0.5.6';source_commit=$info.SourceCommit;api_sha256=$info.ApiSha256;web_sha256=$info.WebSha256;image_id=$patch.new_image;database_changed=$false;api_job=$match.Groups[1].Value;public_verified=$false}
$private=Join-Path $project 'private\desktop056';New-Item -ItemType Directory -Force -Path $private|Out-Null
[IO.File]::WriteAllText((Join-Path $private 'completed.json'),($completed|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
& node.exe (Join-Path $PSScriptRoot 'lib\static-056-public.cjs') $delivery
if($LASTEXITCODE-ne 0){throw 'Files published; public check incomplete. Use 01 with -VerifyOnly, not redeployment or database restore.'}
$completed.public_verified=$true
[IO.File]::WriteAllText((Join-Path $private 'completed.json'),($completed|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
Write-Host 'CLOUD056_VERIFIED; no migration or financial data clearing.'
