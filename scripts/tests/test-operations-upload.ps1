$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression.FileSystem
$project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$builder = Join-Path $project 'scripts\build-operations-deploy.ps1'
$uploader = Join-Path $project 'scripts\upload-operations-upgrade.ps1'
if (-not (Test-Path -LiteralPath $builder)) { throw 'Committed-snapshot deployment builder missing.' }
if (-not (Test-Path -LiteralPath $uploader)) { throw 'Read-only operations uploader missing.' }
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-operations-upload-test-' + [guid]::NewGuid().ToString('N'))
$root = Join-Path $temporary 'project'
function Fixture([string]$Relative, [string]$Text = 'safe committed fixture') {
    $file = Join-Path $root $Relative
    [void](New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($file)) -Force)
    [IO.File]::WriteAllText($file, $Text, [Text.UTF8Encoding]::new($false))
}
function Assert([bool]$Value, [string]$Message) { if (-not $Value) { throw $Message } }
try {
    [void](New-Item -ItemType Directory -Path $root)
    foreach ($file in @('server/Dockerfile','server/docker-entrypoint.sh','server/requirements.txt','server/run.py',
        'server/app/__init__.py','server/app/operations_upgrade.py','server/app/operations_backup.py',
        'server/app/catalog_defaults.py','server/app/package_billing.py','server/app/package_service.py',
        'server/migrations/env.py','server/migrations/versions/20261004_employee_entries.py',
        'server/migrations/versions/20261004_catalog_packages.py','deploy/cloud/docker-compose.prod.yml',
        'deploy/cloud/scripts/operations_preflight.py','client/package.json','client/package-lock.json',
        'mobile/package.json','mobile/package-lock.json','mobile/version.json')) { Fixture $file }
    Fixture 'deploy/cloud/.env.example' 'POSTGRES_PASSWORD=replace-me'
    Fixture 'client/dist/index.html' '<html>desktop</html>'
    Fixture 'mobile/dist/index.html' '<html>mobile</html>'
    Fixture 'client/dist/assets/current.js' 'window.desktopFixture=true'
    Fixture 'mobile/dist/assets/current.js' 'window.mobileFixture=true'
    Fixture 'server/.venv/Scripts/python.exe' 'not a runtime fixture'
    Fixture '.gitignore' "server/.venv/`nclient/dist/`nmobile/dist/`nrelease/`n"
    Push-Location -LiteralPath $root
    try {
        & git.exe init -q
        & git.exe add -- .
        & git.exe -c user.name=Fixture -c user.email=fixture@example.invalid commit -q -m fixture
        Assert ($LASTEXITCODE -eq 0) 'Isolated source fixture commit failed.'
        $commit = (& git.exe rev-parse HEAD).Trim()
    } finally { Pop-Location }
    # User edits and public generated metadata must stay untouched and out of the commit snapshot.
    Fixture 'server/app/catalog_defaults.py' 'USER_UNCOMMITTED_SENTINEL'
    Fixture 'mobile/version.json' 'USER_GENERATED_SENTINEL'
    $result = & $builder -SourceRoot $root
    Assert ($result.SourceCommit -eq $commit) 'Build lost committed source identity.'
    Assert ((Get-Content -LiteralPath (Join-Path $root 'mobile/version.json') -Raw).Trim() -eq 'USER_GENERATED_SENTINEL') 'User metadata was modified.'
    $zip = [IO.Compression.ZipFile]::OpenRead($result.ZipPath)
    try {
        $entry = $zip.GetEntry('xiquan/server/app/catalog_defaults.py')
        $reader = [IO.StreamReader]::new($entry.Open())
        try { Assert ($reader.ReadToEnd() -eq 'safe committed fixture') 'Dirty working file entered reviewed source ZIP.' }
        finally { $reader.Dispose() }
    } finally { $zip.Dispose() }
    function global:ssh.exe { throw 'StageOnly attempted SSH.' }
    function global:scp.exe { throw 'StageOnly attempted SCP.' }
    $runtime = Join-Path $project 'server/.venv/Scripts/python.exe'
    $checked = & $uploader -BundlePath $result.ZipPath -ExpectedSha256 $result.Sha256 -PythonPath $runtime -StageOnly
    Assert ($checked.StageOnly -and $checked.SourceCommit -eq $commit) 'StageOnly did not perform real bundle validation.'
    Assert (-not $checked.CloudDataChanged) 'StageOnly claimed a cloud write.'
    # Windows PowerShell 5.1 -File binds defaults before PSScriptRoot is set.
    # Exercise the same no-PythonPath entry point supplied to the user.
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uploader -BundlePath $result.ZipPath -ExpectedSha256 $result.Sha256 -StageOnly | Out-Null
    Assert ($LASTEXITCODE -eq 0) 'Windows PowerShell default runtime path failed.'
    $refused = $false
    try { & $uploader -BundlePath $result.ZipPath -ExpectedSha256 ('0' * 64) -PythonPath $runtime -StageOnly | Out-Null }
    catch { $refused = $true }
    Assert $refused 'Invalid bundle hash was accepted.'
    # External SSH/SCP are replaced only at the transport boundary; real wrapper
    # validation, command construction and tampered-hash stop behavior still run.
    $global:XiquanFixtureUpload = [pscustomobject]@{ScpCount=0;PreflightCount=0;TamperTool=$false;
        ExpectedSha=$result.Sha256;ToolSha=(Get-FileHash -LiteralPath (Join-Path $project 'deploy/cloud/scripts/operations_preflight.py')).Hash.ToLowerInvariant()}
    function global:scp.exe { $global:XiquanFixtureUpload.ScpCount++; $global:LASTEXITCODE=0 }
    function global:ssh.exe {
        $command = [string]$args[-1]
        $global:LASTEXITCODE=0
        if ($command.StartsWith('umask 077 && mkdir -m 700 /tmp/xiquan-operations-upload-')) { return }
        if ($command.StartsWith('sha256sum ')) {
            $paths=$command.Split(' ')
            Write-Output ($global:XiquanFixtureUpload.ExpectedSha + '  ' + $paths[1])
            $toolHash=$global:XiquanFixtureUpload.ToolSha
            if ($global:XiquanFixtureUpload.TamperTool) { $toolHash='0' * 64 }
            Write-Output ($toolHash + '  ' + $paths[2])
            return
        }
        if ($command.StartsWith('python3 ') -and $command.EndsWith(' --mode preflight')) {
            $global:XiquanFixtureUpload.PreflightCount++
            return
        }
        throw 'Unexpected remote action in read-only wrapper.'
    }
    & $uploader -BundlePath $result.ZipPath -ExpectedSha256 $result.Sha256 -PythonPath $runtime
    Assert ($global:XiquanFixtureUpload.ScpCount -eq 2) 'Expected only source ZIP and reviewed preflight tool.'
    Assert ($global:XiquanFixtureUpload.PreflightCount -eq 1) 'Verified upload did not invoke exactly one preflight.'
    $global:XiquanFixtureUpload.TamperTool=$true
    $refused=$false
    try { & $uploader -BundlePath $result.ZipPath -ExpectedSha256 $result.Sha256 -PythonPath $runtime | Out-Null }
    catch { $refused=$true }
    Assert $refused 'Tampered uploaded tool was executed.'
    Assert ($global:XiquanFixtureUpload.PreflightCount -eq 1) 'Cloud preflight ran after failed remote SHA verification.'
    Write-Host 'OPERATIONS_UPLOAD_TESTS_OK: committed snapshot, preserved user edits, actual ZIP verification, StageOnly no SSH/SCP.'
} finally {
    Remove-Item Function:\global:ssh.exe -ErrorAction SilentlyContinue
    Remove-Item Function:\global:scp.exe -ErrorAction SilentlyContinue
    Remove-Variable -Name XiquanFixtureUpload -Scope Global -ErrorAction SilentlyContinue
    $resolved = [IO.Path]::GetFullPath($temporary)
    $prefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $resolved) -notlike 'xiquan-operations-upload-test-*') { throw 'Unsafe fixture cleanup.' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
}
