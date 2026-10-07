[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$BundlePath,
    [Parameter(Mandatory=$true)][string]$ExpectedSha256,
    [string]$EcsTarget = 'root@39.96.217.210',
    [string]$PythonPath,
    [switch]$StageOnly,
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $PythonPath) { $PythonPath = Join-Path $PSScriptRoot '..\server\.venv\Scripts\python.exe' }
$archive = (Resolve-Path -LiteralPath $BundlePath).Path
$name = Split-Path -Leaf $archive
if ($ExpectedSha256 -notmatch '^[0-9a-f]{64}$' -or $name -notmatch '^xiquan-operations-SOURCE-WEB-[A-Za-z0-9._-]+\.zip$') { throw 'Invalid SOURCE/WEB name or SHA256.' }
if ($EcsTarget -ne 'root@39.96.217.210') { throw 'This reviewed preflight is restricted to the existing ECS target.' }
$tool = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\deploy\cloud\scripts\operations_preflight.py')).Path
$toolHash = (Get-FileHash -LiteralPath $tool -Algorithm SHA256).Hash.ToLowerInvariant()
$checkJson = & $PythonPath $tool --local-check --bundle $archive --expected-sha256 $ExpectedSha256
if ($LASTEXITCODE -ne 0) { throw 'Local SOURCE/WEB validation failed. Nothing uploaded.' }
$checked = ($checkJson -join "`n") | ConvertFrom-Json
if ($StageOnly -or $DryRun) {
    [pscustomobject]@{StageOnly=[bool]$StageOnly;DryRun=[bool]$DryRun;BundlePath=$archive;
        Sha256=$ExpectedSha256;SourceCommit=$checked.source_commit;Mode='preflight';CloudDataChanged=$false}
    return
}
$remoteRoot = '/tmp/xiquan-operations-upload-' + [guid]::NewGuid().ToString('N')
$options = @('-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3')
& ssh.exe @options $EcsTarget ('umask 077 && mkdir -m 700 ' + $remoteRoot)
if ($LASTEXITCODE -ne 0) { throw 'Private remote upload directory could not be created. No running service changed.' }
$remoteArchive = $remoteRoot + '/' + $name
$remoteTool = $remoteRoot + '/operations_preflight.py'
& scp.exe @options -- $archive ($EcsTarget + ':' + $remoteArchive)
if ($LASTEXITCODE -ne 0) { throw 'SOURCE/WEB upload failed. Do not deploy.' }
& scp.exe @options -- $tool ($EcsTarget + ':' + $remoteTool)
if ($LASTEXITCODE -ne 0) { throw 'Reviewed preflight tool upload failed. Do not deploy.' }
$remoteHashes = & ssh.exe @options $EcsTarget ('sha256sum ' + $remoteArchive + ' ' + $remoteTool)
if ($LASTEXITCODE -ne 0) { throw 'Remote SHA256 check failed. Preflight was not run.' }
foreach ($record in @(@($ExpectedSha256,$remoteArchive),@($toolHash,$remoteTool))) {
    $pattern = '^' + [regex]::Escape($record[0]) + '\s+\*?' + [regex]::Escape($record[1]) + '$'
    $matches = @($remoteHashes | Where-Object { $_ -match $pattern })
    if ($matches.Count -ne 1) { throw 'Remote bundle/tool hash mismatch. Preflight was not run.' }
}
& ssh.exe @options $EcsTarget ('python3 ' + $remoteTool + ' --bundle ' + $remoteArchive + ' --expected-sha256 ' + $ExpectedSha256 + ' --mode preflight')
if ($LASTEXITCODE -ne 0) { throw 'Cloud preflight stopped. No migration, account change or cleanup was performed. Send the last error output.' }
Write-Host 'SOURCE/WEB staged and read-only preflight finished. API was not stopped; no program or business data was replaced.'
