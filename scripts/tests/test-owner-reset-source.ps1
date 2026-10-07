$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression.FileSystem
$generator = Join-Path $PSScriptRoot '..\build-owner-reset-source.ps1'
if (-not (Test-Path -LiteralPath $generator -PathType Leaf)) { throw 'Missing SOURCE/WEB archive generator.' }
$fixture = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-source-test-' + [guid]::NewGuid().ToString('N'))
$root = Join-Path $fixture 'project'
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
function Write-Fixture([string]$Relative, [string]$Content = 'safe fixture') {
    $path = Join-Path $root $Relative
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($path)) -Force | Out-Null
    [IO.File]::WriteAllText($path, $Content, (New-Object Text.UTF8Encoding($false)))
}
function Assert-Rejected([scriptblock]$Action, [string]$Label) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw "Expected rejection: $Label" }
}
try {
    foreach ($file in $required) { Write-Fixture $file }
    Write-Fixture 'client/dist/assets/current.js' 'current owner button'
    Write-Fixture 'mobile/dist/assets/current.js' 'current mobile button'
    foreach ($unsafe in @('.env', 'private/android/release.jks', 'deploy/cloud/releases/client-policy.json',
                         'deploy/cloud/mobile/downloads/old.apk', 'server/instance/test.db',
                         'scripts/ssh_old.py', 'client/node_modules/pkg/index.js')) { Write-Fixture $unsafe 'must not ship' }
    $output = Join-Path $root 'release/cloud'
    $first = & $generator -SourceRoot $root -OutputDirectory $output
    if ($first.Label -ne 'SOURCE/WEB') { throw 'Archive must be explicitly labeled SOURCE/WEB.' }
    if ((Get-FileHash -LiteralPath $first.ZipPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $first.Sha256) { throw 'SHA256 mismatch.' }
    $zip = [IO.Compression.ZipFile]::OpenRead($first.ZipPath)
    try {
        foreach ($rawEntry in $zip.Entries) {
            if ($rawEntry.FullName.Contains('\') -or -not $rawEntry.FullName.StartsWith('xiquan/')) {
                throw 'SOURCE/WEB ZIP entry names must be portable Linux paths.'
            }
        }
        $entries = @($zip.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
        foreach ($entry in @('xiquan/client/dist/assets/current.js', 'xiquan/mobile/dist/assets/current.js',
                             'xiquan/deploy/cloud/.env.example', 'xiquan/server/app/reset_service.py',
                             'xiquan/SOURCE-WEB-NOT-PRODUCTION.txt')) {
            if ($entry -notin $entries) { throw "Required ZIP entry absent: $entry" }
        }
        if ($entries -match '(?i)(?:^|/)(?:private|node_modules|instance|downloads|releases)(?:/|$)|ssh_') { throw 'Unsafe ZIP entry.' }
        if ('xiquan/.env' -in $entries) { throw 'Private env entered ZIP.' }
    } finally { $zip.Dispose() }
    $firstHash = $first.Sha256
    $second = & $generator -SourceRoot $root -OutputDirectory $output
    if ($first.ZipPath -eq $second.ZipPath) { throw 'Output names must be unique.' }
    if ((Get-FileHash -LiteralPath $first.ZipPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $firstHash) { throw 'Old archive overwritten.' }
    Write-Fixture 'client/dist/secret.pem' 'private key'
    $before = @(Get-ChildItem -LiteralPath $output -Filter '*.zip').Count
    Assert-Rejected { & $generator -SourceRoot $root -OutputDirectory $output } 'unsafe built entry'
    if (@(Get-ChildItem -LiteralPath $output -Filter '*.zip').Count -ne $before) { throw 'Unsafe archive published.' }
    Remove-Item -LiteralPath (Join-Path $root 'client/dist/secret.pem')
    foreach ($missing in @('server/app/reset_service.py', 'server/app/deployment_checks.py',
                           'server/migrations/versions/20261002_reset_barrier.py',
                           'server/migrations/versions/20261003_preserve_administrators.py',
                           'deploy/cloud/scripts/backup-role.sql')) {
        Remove-Item -LiteralPath (Join-Path $root $missing)
        Assert-Rejected { & $generator -SourceRoot $root -OutputDirectory $output } "absent $missing"
        Write-Fixture $missing
    }
    Write-Host '11 SOURCE/WEB checks passed: actual ZIP contents, hash, label, forbidden exclusions, unique/no overwrite, unsafe rejection, five missing prerequisites.'
} finally {
    $absolute = [IO.Path]::GetFullPath($fixture)
    $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $absolute.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe fixture cleanup.' }
    if (Test-Path -LiteralPath $absolute) { Remove-Item -LiteralPath $absolute -Recurse -Force }
}
