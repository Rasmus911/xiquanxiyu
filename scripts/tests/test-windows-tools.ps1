[CmdletBinding()]
param([ValidateSet('all','build','publish','delivery')][string]$Group = 'all')
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$fixtureRoot = $null
$formalFixtureRoot = $null
$testStages = New-Object 'System.Collections.Generic.List[string]'
$nodeExe = (Get-Command node.exe -CommandType Application | Select-Object -First 1).Source
try {
    foreach ($name in @('build-windows-release','new-desktop-release-key','sign-windows-release','publish-windows-release','build-windows-delivery','test-windows-compat')) {
        $tokens=$null; $errors=$null
        [void][Management.Automation.Language.Parser]::ParseFile((Join-Path $project ('scripts\' + $name + '.ps1')),[ref]$tokens,[ref]$errors)
        if ($errors.Count) { throw ('PowerShell parse errors: ' + $name) }
    }
    if ($Group -in @('all','build')) {
        $previousSigningLink = $env:CSC_LINK
        $signingRejected = $false
        try {
            $env:CSC_LINK = 'isolated-fixture-no-certificate.pfx'
            try { & (Join-Path $project 'scripts\build-windows-release.ps1') -TestOnly -DryRun -BuildId 'tools-regression-dry' | Out-Null }
            catch { $signingRejected = $true }
        } finally { $env:CSC_LINK = $previousSigningLink }
        if (-not $signingRejected) { throw 'Implicit certificate environment was not rejected before build.' }
        & (Join-Path $project 'scripts\build-windows-release.ps1') -TestOnly -DryRun -BuildId 'tools-regression-dry' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Real build wrapper DryRun failed.' }
        & (Join-Path $project 'scripts\build-windows-release.ps1') -TestOnly -DryRun -BuildId 'tools-regression-one' -Targets @('win11-x64') | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Real single-target build DryRun failed.' }
        if (Test-Path -LiteralPath (Join-Path $project 'release\windows\0.4.2\tools-regression-dry')) { throw 'DryRun wrote release files.' }
    }
    if ($Group -in @('all','publish','delivery')) {
        $fixture = (& node.exe (Join-Path $PSScriptRoot 'windows-release-fixture.cjs') --candidate) | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw 'Fixture creation failed.' }
        $fixtureRoot = $fixture.fixtureRoot
        if ($Group -in @('all','publish')) {
            $rejected = $false
            try { & (Join-Path $project 'scripts\publish-windows-release.ps1') -ReleaseRoot $fixture.releaseRoot -DryRun }
            catch { $rejected = $true }
            if (-not $rejected) { throw 'Candidate bypassed the real publisher preflight.' }
            $formal = (& $nodeExe (Join-Path $PSScriptRoot 'windows-release-fixture.cjs') --signed) | ConvertFrom-Json
            if ($LASTEXITCODE -ne 0) { throw 'Formal fixture signing failed.' }
            $formalFixtureRoot = $formal.fixtureRoot
            $policyPath = Join-Path $project 'deploy\cloud\releases\client-policy.json'
            $oldPolicyHash = (Get-FileHash -LiteralPath $policyPath).Hash
            $publishScript = Join-Path $project 'scripts\publish-windows-release.ps1'
            & $publishScript -ReleaseRoot $formal.releaseRoot -StageOnly | Out-Null
            # StageOnly uses Write-Host, so discover this fixture's verified index below.
            $stageParent = Join-Path $project 'release\windows-staging'
            $newStages = @(Get-ChildItem -LiteralPath $stageParent -Directory | Where-Object {
                $testIndex = Join-Path $_.FullName 'delivery-index.json'
                if (Test-Path -LiteralPath $testIndex) {
                    $value = Get-Content -LiteralPath $testIndex -Raw -Encoding UTF8 | ConvertFrom-Json
                    $value.releaseTrust.keyId -eq (Get-Content -LiteralPath (Join-Path $formal.releaseRoot 'delivery-index.json') -Raw -Encoding UTF8 | ConvertFrom-Json).releaseTrust.keyId
                }
            })
            if ($newStages.Count -ne 1) { throw 'StageOnly did not create one verified fixture stage.' }
            $testStages.Add($newStages[0].FullName)
            if (@(Get-ChildItem -LiteralPath (Join-Path $newStages[0].FullName 'updates\desktop') -Recurse -Filter '*.exe').Count -ne 6) { throw 'StageOnly lost an installer.' }
            if ((Get-FileHash -LiteralPath $policyPath).Hash -ne $oldPolicyHash) { throw 'Local mobile/web policy was mutated.' }
            & $publishScript -ReleaseRoot $formal.releaseRoot -StageOnly -Targets @('win11-x64') | Out-Null
            $oneStages = @(Get-ChildItem -LiteralPath $stageParent -Directory | Where-Object {
                $p = Join-Path $_.FullName 'delivery-index.json'
                if (Test-Path -LiteralPath $p) {
                    $i = Get-Content -LiteralPath $p -Raw -Encoding UTF8 | ConvertFrom-Json
                    $i.releaseTrust.keyId -eq (Get-Content -LiteralPath (Join-Path $formal.releaseRoot 'delivery-index.json') -Raw -Encoding UTF8 | ConvertFrom-Json).releaseTrust.keyId -and @($i.targets).Count -eq 1
                }
            })
            if ($oneStages.Count -ne 1) { throw 'Explicit Win11 stage was not unique.' }
            $testStages.Add($oneStages[0].FullName)
            if (@(Get-ChildItem -LiteralPath (Join-Path $oneStages[0].FullName 'updates\desktop') -Recurse -Filter '*.exe').Count -ne 1 -or
                (Test-Path -LiteralPath (Join-Path $oneStages[0].FullName 'releases\client-policy.json'))) { throw 'Win11 stage included unrequested policies/installers.' }
            # Run the actual publisher orchestration with fake external transports only.
            # Node preflight/staging remains real; no network command can escape these functions.
            $global:XiquanTestActualNode = $nodeExe
            $global:XiquanTestTransportCalls = New-Object 'System.Collections.Generic.List[string]'
            function scp.exe {
                param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
                $global:XiquanTestTransportCalls.Add('scp')
                $global:LASTEXITCODE = $global:XiquanTestScpExit
            }
            function ssh.exe {
                param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
                $global:XiquanTestTransportCalls.Add('ssh')
                $global:LASTEXITCODE = $global:XiquanTestSshExit
            }
            function node.exe {
                param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
                if ((Split-Path -Leaf $Arguments[0]) -eq 'windows-public-check.cjs') {
                    $global:XiquanTestTransportCalls.Add('http')
                    $global:LASTEXITCODE = $global:XiquanTestHttpExit
                } else {
                    & $global:XiquanTestActualNode @Arguments
                    $global:LASTEXITCODE = $LASTEXITCODE
                }
            }
            try {
                foreach ($case in @(
                    @{Scp=1;Ssh=0;Http=0;Calls='scp';Reject=$true},
                    @{Scp=0;Ssh=1;Http=0;Calls='scp,ssh';Reject=$true},
                    @{Scp=0;Ssh=0;Http=1;Calls='scp,ssh,http';Reject=$true},
                    @{Scp=0;Ssh=0;Http=0;Calls='scp,ssh,http';Reject=$false}
                )) {
                    $global:XiquanTestScpExit=$case.Scp; $global:XiquanTestSshExit=$case.Ssh; $global:XiquanTestHttpExit=$case.Http
                    $global:XiquanTestTransportCalls.Clear()
                    $wasRejected=$false; $transportError=''
                    try { & $publishScript -ReleaseRoot $formal.releaseRoot | Out-Null } catch { $wasRejected=$true; $transportError=$_.Exception.Message }
                    if ($wasRejected -ne $case.Reject -or ($global:XiquanTestTransportCalls -join ',') -ne $case.Calls) { throw ('Actual publisher transport sequence failed: expected=' + $case.Calls + '; actual=' + ($global:XiquanTestTransportCalls -join ',') + '; error=' + $transportError) }
                }
                if ((Get-FileHash -LiteralPath $policyPath).Hash -ne $oldPolicyHash) { throw 'Transport regression changed mobile/web policy.' }
                Write-Host '4 actual publisher orchestration cases passed with fake SCP/SSH/HTTP only.'
            } finally {
                Remove-Item -LiteralPath Function:\scp.exe,Function:\ssh.exe,Function:\node.exe -ErrorAction SilentlyContinue
                Remove-Variable -Name XiquanTestActualNode,XiquanTestTransportCalls,XiquanTestScpExit,XiquanTestSshExit,XiquanTestHttpExit -Scope Global -ErrorAction SilentlyContinue
                # Track only stages bearing this unique fixture public key for cleanup.
                $fixtureKeyId = (Get-Content -LiteralPath (Join-Path $formal.releaseRoot 'delivery-index.json') -Raw -Encoding UTF8 | ConvertFrom-Json).releaseTrust.keyId
                foreach ($directory in Get-ChildItem -LiteralPath $stageParent -Directory) {
                    $testIndex = Join-Path $directory.FullName 'delivery-index.json'
                    if ((Test-Path -LiteralPath $testIndex) -and
                        (Get-Content -LiteralPath $testIndex -Raw -Encoding UTF8 | ConvertFrom-Json).releaseTrust.keyId -eq $fixtureKeyId -and
                        -not $testStages.Contains($directory.FullName)) { $testStages.Add($directory.FullName) }
                }
            }
        }
        if ($Group -in @('all','delivery')) {
            $output = Join-Path $fixtureRoot 'bundles'; [void](New-Item -ItemType Directory -Path $output)
            [IO.File]::WriteAllText((Join-Path $output 'old.zip'), 'sentinel')
            & (Join-Path $project 'scripts\build-windows-delivery.ps1') -ReleaseRoot $fixture.releaseRoot -OutputDirectory $output -Candidate
            if ($LASTEXITCODE -ne 0) { throw 'Real candidate ZIP script failed.' }
            if ([IO.File]::ReadAllText((Join-Path $output 'old.zip')) -ne 'sentinel') { throw 'Old ZIP was modified.' }
            $zip = @(Get-ChildItem -LiteralPath $output -Filter '*CANDIDATE*.zip')
            if ($zip.Count -ne 1) { throw 'No unique candidate ZIP.' }
            $archive = [IO.Compression.ZipFile]::OpenRead($zip[0].FullName)
            try {
                if (@($archive.Entries | Where-Object { $_.FullName.EndsWith('.exe') }).Count -ne 6) { throw 'ZIP does not contain six installers.' }
                if (@($archive.Entries | Where-Object { $_.FullName.Contains('\') -or $_.FullName -match '\.env|\.jks|private\.pem' }).Count) { throw 'ZIP contains forbidden entries.' }
            } finally { $archive.Dispose() }
            $oneOutput = Join-Path $fixtureRoot 'one-bundle'
            & (Join-Path $project 'scripts\build-windows-delivery.ps1') -ReleaseRoot $fixture.releaseRoot -OutputDirectory $oneOutput -Candidate -Targets @('win11-x64') | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Single-target ZIP wrapper failed.' }
            $oneZip = @(Get-ChildItem -LiteralPath $oneOutput -Filter '*.zip')
            if ($oneZip.Count -ne 1) { throw 'Single-target ZIP was not unique.' }
            $archive = [IO.Compression.ZipFile]::OpenRead($oneZip[0].FullName)
            try {
                $installers = @($archive.Entries | Where-Object { $_.FullName.EndsWith('.exe') })
                if ($installers.Count -ne 1 -or -not $installers[0].FullName.EndsWith('-win11-x64.exe')) { throw 'Single-target ZIP has incorrect installers.' }
            } finally { $archive.Dispose() }
        }
    }
    Write-Host ('Windows tools regression passed: ' + $Group + '; no SDK download/SSH/cloud transaction.')
} finally {
    foreach ($cleanupRoot in @($fixtureRoot,$formalFixtureRoot)) {
      if ($cleanupRoot) {
        $absolute = [IO.Path]::GetFullPath($cleanupRoot)
        $tempPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        if (-not $absolute.StartsWith($tempPrefix,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $absolute) -notlike 'xiquan-release-test-*') { throw 'Unsafe fixture cleanup.' }
        Remove-Item -LiteralPath $absolute -Recurse -Force
      }
    }
    foreach ($testStage in $testStages) {
        $absolute = [IO.Path]::GetFullPath($testStage)
        $stagePrefix = [IO.Path]::GetFullPath((Join-Path $project 'release\windows-staging')).TrimEnd('\') + '\'
        if (-not $absolute.StartsWith($stagePrefix,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $absolute) -notlike 'xiquan-windows-*') { throw 'Unsafe test stage cleanup.' }
        Remove-Item -LiteralPath $absolute -Recurse -Force
    }
}
