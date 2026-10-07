$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$helper = Join-Path $project 'scripts/lib/stock-source.cjs'
if (-not (Test-Path -LiteralPath $helper)) { throw 'Stock committed source verifier must exist.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-stock-source-test-' + [guid]::NewGuid().ToString('N'))
$root = Join-Path $temporary 'repo'
function Put([string]$Name,[string]$Text) {
    $file = Join-Path $root $Name
    [void](New-Item -ItemType Directory -Path (Split-Path -Parent $file) -Force)
    [IO.File]::WriteAllText($file,$Text,[Text.UTF8Encoding]::new($false))
}
function Run([string[]]$Arguments, [bool]$Success = $true) {
    $oldPreference = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { $output = & node.exe $helper @Arguments 2>&1 } finally { $ErrorActionPreference = $oldPreference }
    if (($LASTEXITCODE -eq 0) -ne $Success) { throw ('Unexpected stock-source result: ' + ($output -join "`n")) }
    if ($Success) { return (($output -join "`n") | ConvertFrom-Json) }
}
try {
    Put 'client/package.json' '{"version":"0.4.4"}'
    Put 'mobile/version.json' '{"version":"1.2.3","versionCode":10,"minimumVersionCode":9}'
    foreach ($name in @('server/migrations/versions/20261005_independent_stock.py','scripts/stock_import.py',
        'docs/inventory/2026-10-05-photo-stock-review.csv','docs/inventory/2026-10-05-photo-stock-notes.md',
        'docs/inventory/2026-10-05-photo-stock-import.md')) { Put $name '# reviewed source' }
    Put '.env' 'excluded'
    Put 'release/old.exe' 'excluded'
    & git.exe -C $root init -q
    & git.exe -C $root add -- .
    & git.exe -C $root -c user.name=Fixture -c user.email=fixture@example.invalid commit -q -m fixture
    $contract = Run @('inspect',$root)
    if ($contract.schema_head -ne '20261005_independent_stock' -or $contract.files.Count -ne 7) { throw 'Exact reviewed inventory is wrong.' }
    Put 'client/src/untracked.ts' 'excluded untracked'
    $again = Run @('inspect',$root)
    if ($again.files.Count -ne 7) { throw 'Untracked source entered committed inventory.' }
    Put 'scripts/stock_import.py' 'uncommitted'
    Run @('inspect',$root) $false
    # Archive readback runs against a hand-created fixture with manifest and asset inventory.
    $payload = Join-Path $temporary 'payload/xiquan'
    [void](New-Item -ItemType Directory -Path $payload -Force)
    $contract.files = @()
    foreach ($name in @('server/migrations/versions/20261005_independent_stock.py','client/package.json','mobile/version.json','client/dist/index.html','mobile/dist/index.html',
        'scripts/stock_import.py','docs/inventory/2026-10-05-photo-stock-review.csv',
        'docs/inventory/2026-10-05-photo-stock-notes.md','docs/inventory/2026-10-05-photo-stock-import.md')) {
        $target = Join-Path $payload $name
        [void](New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force)
        $value = 'fixture'
        if ($name -eq 'client/package.json') { $value = '{"version":"0.4.4"}' }
        if ($name -eq 'mobile/version.json') { $value = '{"version":"1.2.3","versionCode":10}' }
        [IO.File]::WriteAllText($target,$value,[Text.UTF8Encoding]::new($false))
        $contract.files += [pscustomobject]@{file=$name;size=(Get-Item $target).Length;sha256=(Get-FileHash $target).Hash.ToLowerInvariant()}
    }
    $manifestPath = Join-Path $payload 'source-manifest.json'
    [IO.File]::WriteAllText($manifestPath,($contract | ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $payload 'SOURCE-WEB-NOT-PRODUCTION.txt'),'pending')
    . (Join-Path $project 'scripts/lib/cloud-archive.ps1')
    $zip = Join-Path $temporary 'fixture.zip'
    New-CloudReleaseArchive -SourceDirectory $payload -DestinationPath $zip -PortableEntryNames
    $read = Run @('archive',$zip,$contract.source_commit)
    if ($read.schema_head -ne '20261005_independent_stock') { throw 'Archive contract missing.' }
    Run @('archive',$zip,('f' * 40)) $false
    $archive = [IO.Compression.ZipFile]::Open($zip,[IO.Compression.ZipArchiveMode]::Update)
    try { [void]$archive.CreateEntry('xiquan/client/dist/index.html') } finally { $archive.Dispose() }
    Run @('archive',$zip,$contract.source_commit) $false
    Write-Host 'Stock source checks passed: exact inventory, dirty rejection, ZIP readback, wrong commit and duplicate rejection.'
} finally {
    $resolved = [IO.Path]::GetFullPath($temporary)
    if (-not $resolved.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()),[StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $resolved) -notlike 'xiquan-stock-source-test-*') { throw 'Unsafe fixture cleanup.' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
