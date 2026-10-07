$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$helper = Join-Path $PSScriptRoot '..\lib\release-policy.ps1'
. $helper

function Assert-Equal {
    param(
        [Parameter(Mandatory)]$Actual,
        [Parameter(Mandatory)]$Expected,
        [Parameter(Mandatory)][string]$Message
    )
    if ($Actual -ne $Expected) {
        throw "$Message Expected '$Expected', got '$Actual'."
    }
}

function Assert-Throws {
    param(
        [Parameter(Mandatory)][scriptblock]$Action,
        [Parameter(Mandatory)][string]$Pattern
    )
    try {
        & $Action
    }
    catch {
        if ($_.Exception.Message -notmatch $Pattern) {
            throw "Expected error matching '$Pattern', got '$($_.Exception.Message)'."
        }
        return
    }
    throw "Expected an error matching '$Pattern', but no error was thrown."
}

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-policy-' + [guid]::NewGuid().ToString('N'))

try {
    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    $path = Join-Path $tempRoot 'client-policy.json'
    @{
        schemaVersion = 1
        desktop = @{
            latestVersion = '0.2.5'
            minimumVersion = '0.2.3'
            required = $false
        }
        android = @{
            latestVersion = '1.0.3'
            latestVersionCode = 4
            minimumVersionCode = 1
            required = $false
        }
        web = @{
            buildId = 'old'
            required = $false
        }
    } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding utf8

    Update-ClientReleasePolicy -Path $path -Platform android -Release @{
        latestVersion = '1.1.0'
        latestVersionCode = 5
        minimumVersionCode = 4
        required = $false
        downloadUrl = 'https://api.pqxqxy.xyz/mobile/downloads/xiquan-mobile-ordering-1.1.0.apk'
        sha256 = ('a' * 64)
        releaseNotes = @('覆盖更新')
        publishedAt = '2026-09-27T12:00:00+08:00'
    }

    $actual = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
    Assert-Equal -Actual $actual.android.latestVersionCode -Expected 5 -Message 'Android versionCode was not updated.'
    Assert-Equal -Actual $actual.desktop.latestVersion -Expected '0.2.5' -Message 'Desktop policy was overwritten.'
    Assert-Equal -Actual $actual.schemaVersion -Expected 1 -Message 'Schema version changed.'
    Assert-Equal -Actual (Test-Path -LiteralPath "$path.new") -Expected $false -Message 'Temporary policy file was not removed.'

    Assert-Throws -Pattern 'minimumVersionCode' -Action {
        Update-ClientReleasePolicy -Path $path -Platform android -Release @{
            latestVersion = '1.1.0'
            latestVersionCode = 5
            minimumVersionCode = 6
            required = $true
            downloadUrl = 'https://api.pqxqxy.xyz/mobile/downloads/xiquan-mobile-ordering-1.1.0.apk'
            sha256 = ('b' * 64)
            releaseNotes = @('强制更新')
            publishedAt = '2026-09-27T12:00:00+08:00'
        }
    }

    Assert-Throws -Pattern 'sha256' -Action {
        Update-ClientReleasePolicy -Path $path -Platform desktop -Release @{
            latestVersion = '0.3.0'
            minimumVersion = '0.2.5'
            required = $false
            downloadUrl = 'https://api.pqxqxy.xyz/updates/Xiquan-Bathhouse-Setup-0.3.0.exe'
            sha256 = 'not-a-hash'
            releaseNotes = @('更新中心')
            publishedAt = '2026-09-27T12:00:00+08:00'
        }
    }

    Write-Host 'Release policy tests passed.' -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
