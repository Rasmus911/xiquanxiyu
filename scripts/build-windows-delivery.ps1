[CmdletBinding()]
param([Parameter(Mandatory)][string]$ReleaseRoot, [string]$OutputDirectory, [switch]$Candidate,
    [ValidateSet('win7-x86','win7-x64','win10-x86','win10-x64','win11-x86','win11-x64')]
    [string[]]$Targets = @('win7-x86','win7-x64','win10-x86','win10-x64','win11-x86','win11-x64'))
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$root = (Resolve-Path -LiteralPath $ReleaseRoot -ErrorAction Stop).Path
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $project 'release\windows-bundles' }
$output = [IO.Path]::GetFullPath($OutputDirectory)
[void](New-Item -ItemType Directory -Path $output -Force)
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-windows-delivery-' + [guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory -Path $temporary)
$bundleRoot = Join-Path $temporary 'xiquan-windows-delivery'
try {
    $mode = 'release'; if ($Candidate) { $mode = 'candidate' }
    & node.exe (Join-Path $PSScriptRoot 'lib\windows-delivery.cjs') $root $bundleRoot $mode ($Targets -join ',')
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $bundleRoot 'SHA256SUMS'))) { throw 'Delivery preflight failed. No ZIP was published.' }
    $index = Get-Content -LiteralPath (Join-Path $bundleRoot 'delivery-index.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $index.complete -or ((-not $Candidate) -and (-not $index.signed))) { throw 'Release index is not complete/verified.' }
    $suffix = ''; if ($Candidate) { $suffix = '-CANDIDATE' }
    $zipName = 'xiquan-windows-' + $index.version + '-' + $index.buildId + $suffix + '-' + [guid]::NewGuid().ToString('N').Substring(0,8) + '.zip'
    $zipPath = Join-Path $output $zipName
    . (Join-Path $PSScriptRoot 'lib\cloud-archive.ps1')
    New-CloudReleaseArchive -SourceDirectory $bundleRoot -DestinationPath $zipPath -PortableEntryNames
    $archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        foreach ($line in Get-Content -LiteralPath (Join-Path $bundleRoot 'SHA256SUMS') -Encoding UTF8) {
            $parts = $line -split '  ',2
            $entry = $archive.GetEntry('xiquan-windows-delivery/' + $parts[1])
            if (-not $entry) { throw 'ZIP is missing an inspected file.' }
            $stream = $entry.Open(); $hashTool = [Security.Cryptography.SHA256]::Create()
            try { $entryHash = ([BitConverter]::ToString($hashTool.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
            finally { $hashTool.Dispose(); $stream.Dispose() }
            if ($entryHash -ne $parts[0]) { throw 'ZIP entry hash mismatch.' }
        }
    } finally { $archive.Dispose() }
    $zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host ('ZIP: ' + $zipPath)
    Write-Host ('SHA256: ' + $zipHash)
} finally {
    $validated = [IO.Path]::GetFullPath($temporary)
    $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $validated.StartsWith($tempPrefix,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $validated) -notlike 'xiquan-windows-delivery-*') { throw 'Unsafe temporary cleanup path.' }
    if (Test-Path -LiteralPath $validated) { Remove-Item -LiteralPath $validated -Recurse -Force }
}
