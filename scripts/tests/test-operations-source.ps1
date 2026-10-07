$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression.FileSystem
$project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$generator = Join-Path $project 'scripts\build-operations-source.ps1'
if (-not (Test-Path -LiteralPath $generator -PathType Leaf)) { throw 'Operations SOURCE/WEB generator is missing.' }
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-operations-source-test-' + [guid]::NewGuid().ToString('N'))
$root = Join-Path $temporary 'project'
function Fixture([string]$Relative, [string]$Text = 'safe fixture') {
    $file = Join-Path $root $Relative
    [void](New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($file)) -Force)
    [IO.File]::WriteAllText($file, $Text, [Text.UTF8Encoding]::new($false))
}
try {
    [void](New-Item -ItemType Directory -Path $root)
    foreach ($file in @('server/Dockerfile','server/docker-entrypoint.sh','server/requirements.txt','server/run.py',
        'server/app/operations_upgrade.py','server/app/operations_backup.py','server/app/catalog_defaults.py',
        'server/app/package_billing.py','server/app/package_service.py',
        'server/migrations/env.py','server/migrations/versions/20261004_employee_entries.py',
        'server/migrations/versions/20261004_catalog_packages.py','deploy/cloud/docker-compose.prod.yml',
        'client/package.json','client/package-lock.json','mobile/package.json','mobile/package-lock.json','mobile/version.json')) { Fixture $file }
    Fixture 'deploy/cloud/.env.example' 'POSTGRES_PASSWORD=replace-me'
    Fixture 'client/dist/index.html' '<html>desktop</html>'
    Fixture 'mobile/dist/index.html' '<html>mobile</html>'
    Fixture 'client/dist/assets/current.js' 'window.testFixture=true'
    Fixture 'mobile/dist/assets/current.js' 'window.mobileFixture=true'
    # Deliberately commit an unsafe sentinel: source whitelist must still exclude it.
    foreach ($file in @('.env','private/key.jks','deploy/cloud/nginx/active.conf',
        'deploy/cloud/updates/old.exe','deploy/cloud/releases/client-policy.json','deploy/cloud/mobile/downloads/old.apk')) { Fixture $file 'must-not-ship' }
    Push-Location -LiteralPath $root
    try {
        & git.exe init -q
        & git.exe add -- .
        & git.exe -c user.name=Fixture -c user.email=fixture@example.invalid commit -q -m fixture
        if ($LASTEXITCODE -ne 0) { throw 'Isolated Git fixture failed.' }
        $commit = (& git.exe rev-parse HEAD).Trim()
    } finally { Pop-Location }
    $result = & $generator -SourceRoot $root
    if ($result.SourceCommit -ne $commit -or $result.Label -ne 'SOURCE/WEB') { throw 'Source identity/label missing.' }
    if ((Get-FileHash -LiteralPath $result.ZipPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $result.Sha256) { throw 'Source ZIP hash mismatch.' }
    $zip = [IO.Compression.ZipFile]::OpenRead($result.ZipPath)
    try {
        $names = @($zip.Entries | ForEach-Object FullName)
        if ($names -match '\\|\.\./|(?:^|/)(private|updates|downloads|node_modules)(?:/|$)|active\.conf') { throw 'Unsafe source entries.' }
        if ('xiquan/.env' -in $names -or 'xiquan/deploy/cloud/releases/client-policy.json' -in $names) { throw 'Production env/policy was packed.' }
        foreach ($name in @('xiquan/source-manifest.json','xiquan/SOURCE-WEB-NOT-PRODUCTION.txt',
            'xiquan/client/dist/assets/current.js','xiquan/mobile/dist/assets/current.js',
            'xiquan/server/app/catalog_defaults.py','xiquan/server/app/package_billing.py',
            'xiquan/server/app/package_service.py',
            'xiquan/server/migrations/versions/20261004_catalog_packages.py')) {
            if ($name -notin $names) { throw ('Missing source ZIP entry: ' + $name) }
        }
    } finally { $zip.Dispose() }
    $originalHash = $result.Sha256
    $second = & $generator -SourceRoot $root
    if ($second.ZipPath -eq $result.ZipPath -or (Get-FileHash -LiteralPath $result.ZipPath).Hash.ToLowerInvariant() -ne $originalHash) { throw 'Old source ZIP overwritten.' }
    Fixture 'client/dist/secret.pem' 'forbidden generated fixture'
    $rejected = $false
    try { & $generator -SourceRoot $root | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw 'Forbidden generated file entered source archive.' }
    Remove-Item -LiteralPath (Join-Path $root 'client/dist/secret.pem')
    Fixture 'server/app/operations_upgrade.py' 'uncommitted change'
    $rejected = $false
    try { & $generator -SourceRoot $root | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw 'Dirty source incorrectly claimed the old commit.' }
    $releaseGenerator = Join-Path $project 'scripts\build-operations-release.ps1'
    if (-not (Test-Path -LiteralPath $releaseGenerator)) { throw 'Win11-only release entry point is missing.' }
    $publicFile = Join-Path $temporary 'release-public-key.pem'
    [IO.File]::WriteAllText($publicFile,"-----BEGIN PUBLIC KEY-----`nMCowBQYDK2VwAyEAg5Euc1O6oXK6xaPLK8bFabECK024fg76iz7g0kjTEo0=`n-----END PUBLIC KEY-----`n",[Text.UTF8Encoding]::new($false))
    & $releaseGenerator -PublicKeyPath $publicFile -SkipSigning -ValidateOnly -BuildId 'operations-tools-fixture-preflight'
    if ($LASTEXITCODE -ne 0) { throw 'Actual Win11 release preflight failed.' }
    if (Test-Path -LiteralPath (Join-Path $project 'release/windows/0.4.3/operations-tools-fixture-preflight')) { throw 'Preflight wrote an installer.' }
    $wrongPublic = & node.exe -e "const c=require('node:crypto');process.stdout.write(c.generateKeyPairSync('ed25519').publicKey.export({type:'spki',format:'pem'}))"
    [IO.File]::WriteAllText($publicFile,($wrongPublic -join "`n") + "`n",[Text.UTF8Encoding]::new($false))
    $rejected = $false
    try { & $releaseGenerator -PublicKeyPath $publicFile -SkipSigning -ValidateOnly | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw 'Replacement trust key was accepted by the actual release entry point.' }
    Write-Host 'Operations source checks passed: real ZIP, SHA, commit, exclusions, no overwrite, forbidden assets and dirty source rejection.'
} finally {
    $resolved = [IO.Path]::GetFullPath($temporary)
    $prefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $resolved) -notlike 'xiquan-operations-source-test-*') { throw 'Unsafe test cleanup path.' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
