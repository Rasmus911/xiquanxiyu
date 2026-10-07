[CmdletBinding()]
param(
    [ValidateSet('preflight','deploy','resume','all')][string]$Mode = 'all',
    [Parameter(Mandatory)][string]$BundlePath,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedSha256,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$SourceCommit,
    [string]$Stage,
    [string]$Job,
    [string]$EcsTarget = 'root@39.96.217.210',
    [switch]$StageOnly
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path -Parent $PSScriptRoot
$bundle=(Resolve-Path -LiteralPath $BundlePath).Path
if((Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash.ToLowerInvariant()-cne $ExpectedSha256){throw 'SOURCE SHA256 mismatch. No connection attempted.'}
if($EcsTarget-notmatch '^[A-Za-z0-9_-]+@[A-Za-z0-9.-]+$'){throw 'Invalid SSH target.'}
if($Mode-in @('deploy','resume') -and $Stage-notmatch '^/opt/xiquan-releases/desktop045-stage-[0-9a-f]{32}$'){throw 'Exact new-release stage required. Do not reuse an old stock/operations stage.'}
if($Mode-eq 'resume' -and $Job-notmatch '^/opt/xiquan-backups/desktop045-cutover-[0-9a-f]{32}$'){throw 'Exact new-release recovery job required.'}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip=[IO.Compression.ZipFile]::OpenRead($bundle)
try{
    $entry=$zip.GetEntry('xiquan/source-manifest.json')
    if(-not $entry){throw 'SOURCE manifest missing.'}
    $reader=[IO.StreamReader]::new($entry.Open(),[Text.Encoding]::UTF8)
    try{$manifest=$reader.ReadToEnd()|ConvertFrom-Json}finally{$reader.Dispose()}
    if($manifest.source_commit-cne $SourceCommit){throw 'SOURCE commit mismatch.'}
    $names=@('desktop_045_deploy.py','desktop_045_guard.py','stock_deploy.py','stock_guard.py',
        'operations_backup_verify.py','operations_preflight.py','operations_deploy.py','operations_offline_build.py')
    $tools=@()
    foreach($name in $names){
        $file=Join-Path $root ('deploy\cloud\scripts\'+$name)
        $hash=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        $record=@($manifest.files|Where-Object{$_.file-ceq ('deploy/cloud/scripts/'+$name)})
        if($record.Count-ne 1 -or $record[0].sha256-cne $hash){throw ('Transport differs from exact SOURCE: '+$name)}
        $tools+=[pscustomobject]@{Name=$name;File=$file;Hash=$hash}
    }
}finally{$zip.Dispose()}
if($StageOnly){[pscustomobject]@{Mode=$Mode;SourceCommit=$SourceCommit;Sha256=$ExpectedSha256;CloudChanged=$false};return}
$options=@('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
$remote='/tmp/xiquan-desktop045-tools-'+[guid]::NewGuid().ToString('N')
& ssh.exe @options $EcsTarget ('umask 077 && mkdir -m 700 '+$remote)
if($LASTEXITCODE-ne 0){throw 'Cannot create private transport folder. No deployment started.'}
$uploads=@($tools|ForEach-Object{[pscustomobject]@{File=$_.File;Hash=$_.Hash;Remote=$remote+'/'+$_.Name}})
if($Mode-in @('preflight','all')){$uploads+=[pscustomobject]@{File=$bundle;Hash=$ExpectedSha256;Remote=$remote+'/source.zip'}}
foreach($item in $uploads){
    & scp.exe @options -- $item.File ($EcsTarget+':'+$item.Remote)
    if($LASTEXITCODE-ne 0){throw 'Upload failed; deployment not invoked.'}
}
$hashes=& ssh.exe @options $EcsTarget ('sha256sum '+(($uploads|ForEach-Object{$_.Remote})-join ' '))
if($LASTEXITCODE-ne 0){throw 'Remote SHA check failed.'}
foreach($item in $uploads){
    $pattern='^'+[regex]::Escape($item.Hash)+'\s+\*?'+[regex]::Escape($item.Remote)+'$'
    if(@($hashes|Where-Object{$_-match $pattern}).Count-ne 1){throw 'Remote SHA mismatch; deployment not invoked.'}
}
if($Mode-in @('preflight','all')){
    $command='python3 '+$remote+'/desktop_045_deploy.py preflight --bundle '+$remote+'/source.zip --sha256 '+$ExpectedSha256+' --commit '+$SourceCommit
    $output=& ssh.exe @options $EcsTarget $command
    if($LASTEXITCODE-ne 0){throw ('Read-only preflight stopped. Transport: '+$remote)}
    $output|ForEach-Object{Write-Host $_}
    $results=@($output|Where-Object{$_-match '^\{"stage":'}|ForEach-Object{$_|ConvertFrom-Json})
    if($results.Count-ne 1 -or $results[0].source_commit-cne $SourceCommit -or $results[0].source_sha256-cne $ExpectedSha256 -or
        $results[0].stage-notmatch '^/opt/xiquan-releases/desktop045-stage-[0-9a-f]{32}$'){throw 'Preflight stage identity invalid.'}
    $Stage=$results[0].stage
    if($Mode-eq 'preflight'){$results[0];return}
}
$confirmation=Read-Host ('Pause writes during verified backup and additive migration. Type UPDATE 0.4.5')
if($confirmation-cne 'UPDATE 0.4.5'){throw 'Update cancelled. Only private staging was created.'}
$action=$Mode; if($action-eq 'all'){$action='deploy'}
$command='python3 '+$remote+'/desktop_045_deploy.py '+$action+' --stage '+$Stage+' --commit '+$SourceCommit
if($action-eq 'resume'){$command+=' --job '+$Job}
& ssh.exe @options $EcsTarget $command
if($LASTEXITCODE-ne 0){throw ('Update stopped; retain PRIVATE_DESKTOP_JOB and FAILED_PHASE. No automatic rollback or healthy-API stop. Transport: '+$remote)}
Write-Host 'Cloud API/web updated. Signed Windows channels must be published separately; test login with existing accounts.'
