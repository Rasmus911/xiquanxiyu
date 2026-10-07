[CmdletBinding()]
param(
    [string]$SourceRoot = (Join-Path $PSScriptRoot '..'),
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'lib\cloud-archive.ps1')
$root = (Resolve-Path -LiteralPath $SourceRoot -ErrorAction Stop).Path
$expectedOutput = [IO.Path]::GetFullPath((Join-Path $root 'release\cloud'))
if (-not $OutputDirectory) { $OutputDirectory = $expectedOutput }
if (-not [IO.Path]::GetFullPath($OutputDirectory).Equals($expectedOutput, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'SOURCE/WEB output must be under this source root release/cloud.'
}
$required = @(
    'server/Dockerfile', 'server/docker-entrypoint.sh', 'server/run.py', 'server/requirements.txt',
    'server/app/deployment_checks.py', 'server/app/reset_service.py', 'server/app/reset_backup.py',
    'server/app/access_policy.py', 'server/app/business_barrier.py', 'server/app/security_spool.py',
    'server/app/models.py', 'server/app/config.py', 'server/app/__init__.py',
    'server/migrations/env.py', 'server/migrations/alembic.ini',
    'server/migrations/versions/65fcdab61618_initial_schema.py',
    'server/migrations/versions/20260930_security_evidence.py',
    'server/migrations/versions/20261002_business_period_reset.py',
    'server/migrations/versions/20261002_reset_barrier.py',
    'server/migrations/versions/20261003_preserve_administrators.py',
    'deploy/cloud/docker-compose.prod.yml', 'deploy/cloud/.env.example',
    'deploy/cloud/scripts/runtime-role.sql', 'deploy/cloud/scripts/reset-role.sql',
    'deploy/cloud/scripts/backup-role.sql', 'docs/2026-10-03云端重置按钮操作.md',
    'client/package.json', 'client/package-lock.json', 'mobile/package.json',
    'mobile/package-lock.json', 'mobile/version.json', 'client/dist/index.html', 'mobile/dist/index.html',
    'client/src/components/settings/BusinessResetPanel.vue', 'client/src/business/reset.ts',
    'mobile/src/components/profile/BusinessResetPanel.vue'
)
foreach ($file in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $root $file) -PathType Leaf)) { throw "Required source/build missing: $file" }
}
$trees = @('server/app', 'server/migrations', 'client/src', 'client/electron', 'client/public',
           'client/dist', 'mobile/src', 'mobile/public', 'mobile/dist', 'mobile/android/app/src/main/java',
           'mobile/android/app/src/main/res')
$exact = $required + @(
    'server/pyproject.toml', 'mobile/index.html', 'client/index.html', 'client/tsconfig.app.json',
    'client/tsconfig.json', 'client/tsconfig.node.json', 'client/vite.config.ts',
    'mobile/tsconfig.json', 'mobile/vite.config.ts', 'mobile/capacitor.config.ts',
    'mobile/android/build.gradle', 'mobile/android/settings.gradle', 'mobile/android/variables.gradle',
    'mobile/android/gradle.properties', 'mobile/android/app/build.gradle', 'mobile/android/app/capacitor.build.gradle',
    'mobile/android/app/src/main/AndroidManifest.xml',
    'deploy/cloud/nginx/http.conf.template', 'deploy/cloud/nginx/https.conf.template',
    'scripts/build-owner-reset-source.ps1', 'scripts/lib/cloud-archive.ps1',
    'scripts/build-web-release.ps1', 'scripts/build-mobile-web.ps1', 'scripts/build-mobile-release.ps1',
    'scripts/publish-web-release.ps1', 'scripts/publish-mobile-release.ps1', 'scripts/publish-electron-update.ps1',
    'scripts/lib/release-policy.ps1', 'scripts/tests/test-owner-reset-source.ps1',
    'scripts/tests/test-mobile-apk-assets.ps1', 'scripts/tests/test-client-update-release.ps1',
    'server/tests/test_deployment_checks.py', 'server/tests/test_access_policy.py',
    'server/tests/test_preserved_administrators.py', 'server/tests/test_administrator_policy_migration.py'
)
$files = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($file in $exact) {
    if (Test-Path -LiteralPath (Join-Path $root $file) -PathType Leaf) { [void]$files.Add($file.Replace('\', '/')) }
}
$skipDirectories = @('node_modules', '__pycache__', '.pytest_cache', '.ruff_cache', '.gradle', '.git', 'build')
foreach ($tree in $trees) {
    $treePath = Join-Path $root $tree
    if (-not (Test-Path -LiteralPath $treePath -PathType Container)) { continue }
    $queue = New-Object 'System.Collections.Generic.Queue[string]'
    $queue.Enqueue($treePath)
    while ($queue.Count) {
        $directory = Get-Item -LiteralPath $queue.Dequeue() -Force
        if ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Source trees must not contain links.' }
        foreach ($entry in Get-ChildItem -LiteralPath $directory.FullName -Force) {
            if ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Source entries must not be links.' }
            if ($entry.PSIsContainer) {
                if ($entry.Name -notin $skipDirectories) { $queue.Enqueue($entry.FullName) }
            } else {
                # Stale APK metadata is not a newly signed mobile release.
                if ($entry.Name -eq 'download-config.json') { continue }
                $relative = $entry.FullName.Substring($root.TrimEnd('\').Length + 1).Replace('\', '/')
                [void]$files.Add($relative)
            }
        }
    }
}
$extensions = @('.py', '.json', '.md', '.txt', '.sql', '.yml', '.yaml', '.sh', '.ps1', '.html',
                '.css', '.js', '.mjs', '.cjs', '.ts', '.vue', '.xml', '.gradle', '.java', '.properties',
                '.svg', '.png', '.ico', '.jpg', '.jpeg', '.webp', '.woff', '.woff2', '.ttf', '.map',
                '.mako', '.ini', '.toml', '.webmanifest', '.template')
foreach ($relative in $files) {
    if ($relative -match '(?i)(^|/)(private|instance|backups|downloads|releases|node_modules|__pycache__)(/|$)|(^|/)ssh_|(^|/)\.env(?:\.|$)' -and
        $relative -ne 'deploy/cloud/.env.example') { throw "Unsafe selected source: $relative" }
    $extension = [IO.Path]::GetExtension($relative).ToLowerInvariant()
    if ($extension -notin $extensions -and $relative -notin @('server/Dockerfile', 'server/migrations/README', 'deploy/cloud/.env.example')) {
        throw "Unsupported selected source type: $relative"
    }
}
function Assert-NoLinkedAncestor([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    $rootPrefix = $root.TrimEnd('\') + '\'
    while ($current.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase) -or $current -eq $root) {
        if (Test-Path -LiteralPath $current) {
            if ((Get-Item -LiteralPath $current -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Source and output paths must not have linked ancestors.'
            }
        }
        if ($current -eq $root) { break }
        $current = [IO.Path]::GetDirectoryName($current)
    }
}
Assert-NoLinkedAncestor $expectedOutput
$stage = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-source-stage-' + [guid]::NewGuid().ToString('N'))
$payload = Join-Path $stage 'xiquan'
$zipPath = $null
$completed = $false
try {
    New-Item -ItemType Directory -Path $payload | Out-Null
    foreach ($relative in $files) {
        Assert-NoLinkedAncestor (Join-Path $root $relative)
        $source = Get-Item -LiteralPath (Join-Path $root $relative) -Force
        if ($source.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Source files must not be links.' }
        $target = Join-Path $payload $relative
        New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($target)) -Force | Out-Null
        Copy-Item -LiteralPath $source.FullName -Destination $target -ErrorAction Stop
    }
    [IO.File]::WriteAllText((Join-Path $payload 'SOURCE-WEB-NOT-PRODUCTION.txt'),
        'SOURCE/WEB update only. Not a signed APK/EXE installer. PG17 role/lock/full restore and Docker acceptance NOT performed. Old client protocol compatibility is NOT verified. Manual maintenance and owner confirmation are required.',
        (New-Object Text.UTF8Encoding($false)))
    New-Item -ItemType Directory -Path $expectedOutput -Force | Out-Null
    $name = 'xiquan-owner-reset-SOURCE-WEB-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff') + '-' + [guid]::NewGuid().ToString('N') + '.zip'
    $zipPath = Join-Path $expectedOutput $name
    New-CloudReleaseArchive -SourceDirectory $payload -DestinationPath $zipPath -PortableEntryNames
    $archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $expected = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
        foreach ($relative in $files) { [void]$expected.Add('xiquan/' + $relative) }
        [void]$expected.Add('xiquan/SOURCE-WEB-NOT-PRODUCTION.txt')
        foreach ($entry in $archive.Entries) {
            $entryName = $entry.FullName.Replace('\', '/')
            if (-not $expected.Remove($entryName)) { throw 'Unexpected or duplicate ZIP entry.' }
            $stream = $entry.Open()
            try { $stream.CopyTo([IO.Stream]::Null) } finally { $stream.Dispose() }
        }
        if ($expected.Count) { throw 'ZIP missing selected sources.' }
    } finally { $archive.Dispose() }
    $hash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $completed = $true
    [pscustomobject]@{ Label = 'SOURCE/WEB'; ZipPath = $zipPath; Sha256 = $hash; FileCount = $files.Count + 1 }
} finally {
    if (-not $completed -and $zipPath -and (Test-Path -LiteralPath $zipPath)) { Remove-Item -LiteralPath $zipPath -Force }
    $absoluteStage = [IO.Path]::GetFullPath($stage)
    $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $absoluteStage.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe staging cleanup.' }
    if (Test-Path -LiteralPath $absoluteStage) { Remove-Item -LiteralPath $absoluteStage -Recurse -Force }
}
