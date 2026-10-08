$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$builder = Join-Path $projectRoot 'scripts\build-mobile-release.ps1'
$validator = Join-Path $projectRoot 'scripts\lib\stock-mobile.ps1'
$apk = Join-Path $projectRoot 'deploy\cloud\mobile\downloads\xiquan-mobile-ordering-1.2.3.apk'
$previousApk = Join-Path $projectRoot 'deploy\cloud\mobile\downloads\xiquan-mobile-ordering-1.2.2.apk'
$destination = Join-Path $PSScriptRoot 'xiquan-mobile-ordering-1.2.3.apk'
if (Test-Path -LiteralPath $destination) { throw 'A delivered APK already exists. Keep it; do not overwrite it blindly.' }
Write-Host 'Use your ORIGINAL Android certificate and enter passwords only in the hidden prompts.'
Write-Host 'Do not enable transcript/debug logging or send passwords to chat.'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $builder -Version '1.2.3' -VersionCode 10 -MinimumVersionCode 9 -ReleaseNotes 'Independent stock and manual consumables upgrade'
if ($LASTEXITCODE -ne 0) { throw 'Android build failed. No APK copied or uploaded.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $validator -ApkPath $apk -PreviousApkPath $previousApk
if ($LASTEXITCODE -ne 0) { throw 'Original Android certificate verification failed. No APK copied or uploaded.' }
$expected = (Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash
Copy-Item -LiteralPath $apk -Destination $destination
if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -cne $expected) { throw 'Delivered APK hash differs. Do not use the copy.' }
Write-Host ('APK_READY: ' + $destination)
Write-Host ('SHA256: ' + $expected.ToLowerInvariant())
Write-Host 'No cloud upload, Windows signing or publication was performed.'
