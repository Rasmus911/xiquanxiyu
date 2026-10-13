[CmdletBinding()]
param([string]$EcsTarget='root@39.96.217.210')
$ErrorActionPreference='Stop'
$delivery=$PSScriptRoot
$info=Get-Content -LiteralPath (Join-Path $delivery '交付信息.json') -Raw -Encoding UTF8|ConvertFrom-Json
$root=$info.ProjectRoot
& node.exe (Join-Path $root 'scripts\lib\desktop-054.cjs') verify-delivery $delivery
if($LASTEXITCODE-ne 0){throw 'Delivery verification failed. No connection.'}
$result=& (Join-Path $root 'scripts\invoke-desktop-054.ps1') -Mode all -BundlePath (Join-Path $delivery $info.SourceZipFile) `
    -ExpectedSha256 $info.SourceSha256 -SourceCommit $info.SourceCommit -EcsTarget $EcsTarget
if(-not $result.CloudChanged -or $result.Job-notmatch '^/opt/xiquan-backups/desktop054-cutover-[0-9a-f]{32}$'){throw 'Exact completed cloud job missing; do not publish.'}
. (Join-Path $root 'scripts\lib\desktop-054-transport.ps1')
$options=@('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
$receipt=Invoke-TokenNative -Executable 'ssh.exe' -Arguments ($options+@($EcsTarget,('cat '+$result.Job+'/completed.json'))) -TimeoutSeconds 60 -Label 'DESKTOP054 completion receipt'
if($receipt.ExitCode-ne 0){throw 'Completed receipt could not be read; retain job, do not redeploy.'}
$data=$receipt.Stdout|ConvertFrom-Json
if($data.phase-cne 'completed' -or $data.target_schema-cne '20261013_wristband_chip' -or
    $data.source_commit-cne $info.SourceCommit -or $data.source_sha256-cne $info.SourceSha256){throw 'Completed receipt identity differs.'}
$private=Join-Path $root 'private\desktop054'
New-Item -ItemType Directory -Force -Path $private|Out-Null
[IO.File]::WriteAllText((Join-Path $private 'completed.json'),$receipt.Stdout,[Text.UTF8Encoding]::new($false))
Write-Host 'Cloud completion receipt retained. Desktop signing/publication and Android build/publication can follow.'
