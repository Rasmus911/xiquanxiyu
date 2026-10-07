[CmdletBinding()]
param([string]$SourceRoot = (Join-Path $PSScriptRoot '..'), [switch]$Stock, [string]$AssetSourceCommit)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib\cloud-archive.ps1')
$root = (Resolve-Path -LiteralPath $SourceRoot -ErrorAction Stop).Path
$inspect = @'
const {spawnSync}=require('node:child_process');const root=process.argv[1];
const security=require(process.argv[2]);
function git(args){const r=spawnSync('git',args,{cwd:root,encoding:'utf8',windowsHide:true,maxBuffer:16*1024*1024});if(r.status!==0)throw Error('Source must be committed and clean before packaging');return r.stdout;}
const commit=git(['rev-parse','HEAD']).trim();if(!/^[0-9a-f]{40}$/.test(commit))throw Error('Source commit unavailable');
git(['diff','--quiet','HEAD','--']);
const tracked=new Set(git(['ls-files','-z']).split('\0').filter(Boolean));
const files=security.enumerateSourceFiles(root).filter(p=>tracked.has(p)&&p!=='mobile/public/download-config.json');
security.assertSourceSafe(root,files);process.stdout.write(JSON.stringify({commit,files}));
'@
$inputJson = & node.exe -e $inspect $root (Join-Path $PSScriptRoot 'lib\source-security.cjs')
if ($LASTEXITCODE -ne 0) { throw 'SOURCE/WEB source preflight failed; no ZIP created.' }
$source = $inputJson | ConvertFrom-Json
$stockContract = $null
if ($Stock) {
    $contractJson = & node.exe (Join-Path $PSScriptRoot 'lib\stock-source.cjs') inspect $root
    if ($LASTEXITCODE -ne 0) { throw 'Committed stock source preflight failed.' }
    $stockContract = $contractJson | ConvertFrom-Json
    if ($AssetSourceCommit -ne $source.commit -or $stockContract.source_commit -ne $source.commit) { throw 'Fresh stock assets must match committed source.' }
}
$files = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
foreach ($file in $source.files) { [void]$files.Add($file) }
foreach ($file in @('server/Dockerfile','server/docker-entrypoint.sh','server/requirements.txt','server/run.py',
    'server/app/operations_upgrade.py','server/app/operations_backup.py','server/app/catalog_defaults.py',
    'server/app/package_billing.py','server/app/package_service.py',
    'server/migrations/env.py','server/migrations/versions/20261004_employee_entries.py',
    'server/migrations/versions/20261004_catalog_packages.py','deploy/cloud/docker-compose.prod.yml',
    'client/package.json','client/package-lock.json','mobile/package.json','mobile/package-lock.json','mobile/version.json')) {
    if (-not $Stock -and -not $files.Contains($file)) { throw ('Required committed source missing: ' + $file) }
}
function Assert-NoLinks([string]$Path, [string]$Boundary) {
    $current = [IO.Path]::GetFullPath($Path)
    $boundaryPath = [IO.Path]::GetFullPath($Boundary).TrimEnd('\')
    if (-not ($current -eq $boundaryPath -or $current.StartsWith($boundaryPath + '\',[StringComparison]::OrdinalIgnoreCase))) { throw 'Path outside source/output boundary.' }
    while ($current) {
        if ((Test-Path -LiteralPath $current) -and ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Source/output linked ancestor forbidden.' }
        if ($current -eq $boundaryPath) { break }
        $current = [IO.Path]::GetDirectoryName($current)
    }
}
$assetExtensions = @('.html','.js','.css','.json','.svg','.png','.jpg','.jpeg','.webp','.ico','.woff','.woff2','.ttf','.webmanifest')
foreach ($tree in @('client/dist','mobile/dist')) {
    $directory = Join-Path $root $tree
    if (-not (Test-Path -LiteralPath (Join-Path $directory 'index.html') -PathType Leaf)) { throw ('Frontend build missing: ' + $tree) }
    $queue = New-Object 'System.Collections.Generic.Queue[string]'; $queue.Enqueue($directory)
    while ($queue.Count) {
        $current = $queue.Dequeue(); Assert-NoLinks $current $root
        foreach ($entry in Get-ChildItem -LiteralPath $current -Force) {
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Generated asset links forbidden.' }
            if ($entry.PSIsContainer) { $queue.Enqueue($entry.FullName); continue }
            if ($entry.Name -eq 'download-config.json') { continue }
            if ($entry.Name -match '^(?:\.env|.*(?:private|secret).*)$' -or $entry.Extension.ToLowerInvariant() -notin $assetExtensions) { throw 'Forbidden generated source asset.' }
            [void]$files.Add($entry.FullName.Substring($root.TrimEnd('\').Length + 1).Replace('\','/'))
        }
    }
}
$output = Join-Path $root 'release\cloud'; Assert-NoLinks $output $root
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-operations-source-' + [guid]::NewGuid().ToString('N'))
$payload = Join-Path $temporary 'xiquan'
$zipPath = $null; $complete = $false
try {
    [void](New-Item -ItemType Directory -Path $payload)
    $records = @()
    foreach ($relative in @($files | Sort-Object)) {
        $original = Join-Path $root $relative; Assert-NoLinks $original $root
        $target = Join-Path $payload $relative
        [void](New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($target)) -Force)
        Copy-Item -LiteralPath $original -Destination $target
        if ($Stock -and $relative -notmatch '^(client|mobile)/dist/') {
            $expectedRecord = @($stockContract.files | Where-Object { $_.file -ceq $relative })
            if ($expectedRecord.Count -ne 1 -or (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedRecord[0].sha256) { throw 'Stock committed input changed while copying.' }
        }
        if ($relative.EndsWith('.sh')) {
            $text = [IO.File]::ReadAllText($target,[Text.Encoding]::UTF8).Replace("`r`n","`n")
            [IO.File]::WriteAllText($target,$text,[Text.UTF8Encoding]::new($false))
        }
        $records += [ordered]@{file=$relative;size=(Get-Item -LiteralPath $target).Length;
            sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()}
    }
    $manifest = [ordered]@{schema=1;label='SOURCE/WEB';source_commit=$source.commit;files=$records;
        production_ready=$false;pending=@('pg17-roles-concurrency','actual-isolated-restore','original-signatures','real-device-tests','user-cloud-deployment')}
    if ($Stock) {
        foreach ($key in @('asset_source_commit','schema_head','required_migration','desktop_version','android_version','android_version_code')) {
            $manifest[$key] = $stockContract.$key
        }
    }
    [IO.File]::WriteAllText((Join-Path $payload 'source-manifest.json'),($manifest | ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $payload 'SOURCE-WEB-NOT-PRODUCTION.txt'),
        'SOURCE/WEB only. No signed EXE/APK, credentials or published update feeds. No production deployment, PG17 role/concurrency or actual restore acceptance has been performed.',[Text.UTF8Encoding]::new($false))
    [void](New-Item -ItemType Directory -Path $output -Force)
    $prefix = 'xiquan-operations-SOURCE-WEB-'; if ($Stock) { $prefix = 'xiquan-stock-SOURCE-WEB-' }
    $zipPath = Join-Path $output ($prefix + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8) + '.zip')
    New-CloudReleaseArchive -SourceDirectory $payload -DestinationPath $zipPath -PortableEntryNames
    $zip = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $expected = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([StringComparer]::Ordinal)
        foreach ($record in $records) { $expected.Add('xiquan/' + $record.file,$record.sha256) }
        foreach ($name in @('source-manifest.json','SOURCE-WEB-NOT-PRODUCTION.txt')) {
            $expected.Add('xiquan/' + $name,(Get-FileHash -LiteralPath (Join-Path $payload $name) -Algorithm SHA256).Hash.ToLowerInvariant())
        }
        foreach ($entry in $zip.Entries) {
            if (-not $expected.ContainsKey($entry.FullName)) { throw 'Unexpected or repeated ZIP entry.' }
            $stream = $entry.Open(); $sha = [Security.Cryptography.SHA256]::Create()
            try { $digest = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-','').ToLowerInvariant() }
            finally { $stream.Dispose(); $sha.Dispose() }
            if ($digest -ne $expected[$entry.FullName]) { throw 'ZIP readback hash mismatch.' }
            [void]$expected.Remove($entry.FullName)
        }
        if ($expected.Count) { throw 'ZIP is missing reviewed source files.' }
    } finally { $zip.Dispose() }
    $complete = $true
    [pscustomobject]@{Label='SOURCE/WEB';ZipPath=$zipPath;Sha256=(Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant();SourceCommit=$source.commit;FileCount=$records.Count}
} finally {
    if (-not $complete -and $Stock) { Write-Warning ('Failed stock package evidence retained: ' + $temporary + '; ZIP: ' + $zipPath) }
    if (-not $complete -and -not $Stock -and $zipPath -and (Test-Path -LiteralPath $zipPath)) { Remove-Item -LiteralPath $zipPath -Force }
    $resolved = [IO.Path]::GetFullPath($temporary)
    $prefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $resolved) -notlike 'xiquan-operations-source-*') { throw 'Unsafe source staging cleanup.' }
    if (($complete -or -not $Stock) -and (Test-Path -LiteralPath $resolved)) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
