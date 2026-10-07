[CmdletBinding()]
param([string]$SourceRoot)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $SourceRoot) { $SourceRoot = Join-Path $PSScriptRoot '..' }
$root = (Resolve-Path -LiteralPath $SourceRoot).Path
$commit = (& git.exe -C $root rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') { throw 'Committed source identity unavailable.' }
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-operations-deploy-' + [guid]::NewGuid().ToString('N'))
$checkout = Join-Path $temporary 'committed-source'
function Copy-ReviewedAssets([string]$Area) {
    $original = Join-Path $root ($Area + '\dist')
    if (-not (Test-Path -LiteralPath (Join-Path $original 'index.html') -PathType Leaf)) { throw ('Built assets missing: ' + $Area) }
    $targetRoot = Join-Path $checkout ($Area + '\dist')
    $queue = New-Object 'System.Collections.Generic.Queue[string]'
    $queue.Enqueue($original)
    while ($queue.Count -gt 0) {
        $directory = $queue.Dequeue()
        if ((Get-Item -LiteralPath $directory).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked built asset directory forbidden.' }
        foreach ($entry in Get-ChildItem -LiteralPath $directory -Force) {
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked built asset forbidden.' }
            if ($entry.PSIsContainer) { $queue.Enqueue($entry.FullName); continue }
            if ($entry.Name -eq 'download-config.json') { continue }
            $relative = $entry.FullName.Substring($original.TrimEnd('\').Length + 1)
            $destination = Join-Path $targetRoot $relative
            [void](New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($destination)) -Force)
            Copy-Item -LiteralPath $entry.FullName -Destination $destination
        }
    }
}
try {
    [void](New-Item -ItemType Directory -Path $temporary)
    # Local Git transport only. Never reset, stage or modify the user's working files.
    & git.exe clone --quiet --no-local --no-hardlinks -- $root $checkout
    if ($LASTEXITCODE -ne 0) { throw 'Local committed-source snapshot failed.' }
    $snapshotCommit = (& git.exe -C $checkout rev-parse HEAD).Trim()
    if ($snapshotCommit -ne $commit) { throw 'Source HEAD changed during snapshot; retry after inspecting Git.' }
    foreach ($required in @('server/app/operations_backup.py','deploy/cloud/scripts/operations_preflight.py')) {
        if (-not (Test-Path -LiteralPath (Join-Path $checkout $required) -PathType Leaf)) { throw ('Required committed deployment source missing: ' + $required) }
    }
    Copy-ReviewedAssets 'client'
    Copy-ReviewedAssets 'mobile'
    $result = & (Join-Path $PSScriptRoot 'build-operations-source.ps1') -SourceRoot $checkout
    if ($result.SourceCommit -ne $commit) { throw 'SOURCE/WEB commit mismatch.' }
    $outputRoot = Join-Path $root 'release\cloud'
    if ((Test-Path -LiteralPath $outputRoot) -and ((Get-Item -LiteralPath $outputRoot).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Linked output folder forbidden.' }
    [void](New-Item -ItemType Directory -Path $outputRoot -Force)
    $destination = Join-Path $outputRoot (Split-Path -Leaf $result.ZipPath)
    if (Test-Path -LiteralPath $destination) { throw 'Existing SOURCE/WEB ZIP must not be overwritten.' }
    Copy-Item -LiteralPath $result.ZipPath -Destination $destination
    $hash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $result.Sha256) { throw 'Copied SOURCE/WEB hash mismatch; do not upload.' }
    $record = [ordered]@{ZipPath=$destination;Sha256=$hash;SourceCommit=$commit;FileCount=$result.FileCount;
        Scope='SOURCE/WEB staging only';InstallersRebuilt=$false;Uploaded=$false}
    $index = $destination + '.json'
    [IO.File]::WriteAllText($index,($record | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    [pscustomobject]$record
} finally {
    $resolved = [IO.Path]::GetFullPath($temporary)
    $prefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $resolved) -notlike 'xiquan-operations-deploy-*') { throw 'Unsafe source snapshot cleanup.' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
