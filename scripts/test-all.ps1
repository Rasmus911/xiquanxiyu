$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path

function Assert-LastExitCode {
    param([Parameter(Mandatory)][string]$Label)
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE." }
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'scripts\tests\test-release-policy.ps1')
Assert-LastExitCode 'Release policy tests'

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'scripts\tests\test-security-release-bundle.ps1')
Assert-LastExitCode 'Security release bundle tests'

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'scripts\tests\test-cloud-archive.ps1')
Assert-LastExitCode 'Cloud archive lock/retry tests'

Set-Location -LiteralPath (Join-Path $projectRoot "server")
& ".\.venv\Scripts\ruff.exe" check app tests
Assert-LastExitCode 'Server lint'
& ".\.venv\Scripts\python.exe" -m pytest -q
Assert-LastExitCode 'Server tests'

Set-Location -LiteralPath (Join-Path $projectRoot "client")
& npm.cmd run type-check
Assert-LastExitCode 'Desktop type check'
& npm.cmd test
Assert-LastExitCode 'Desktop tests'
& npm.cmd run build
Assert-LastExitCode 'Desktop build'

Set-Location -LiteralPath (Join-Path $projectRoot "mobile")
& npm.cmd test
Assert-LastExitCode 'Mobile tests'
& npm.cmd run type-check
Assert-LastExitCode 'Mobile type check'
& npm.cmd run build
Assert-LastExitCode 'Mobile web build'
& npm.cmd exec cap sync android
Assert-LastExitCode 'Capacitor Android sync'

$availableDrive = @('Z', 'Y', 'X', 'W') | Where-Object { -not (Test-Path ("${_}:\")) } | Select-Object -First 1
if (-not $availableDrive) { throw 'No free temporary drive letter is available for Android tests.' }
$driveRoot = "${availableDrive}:"
& subst.exe $driveRoot $projectRoot
Assert-LastExitCode 'Temporary Android path mapping'
try {
    Set-Location -LiteralPath "$driveRoot\mobile\android"
    & '.\gradlew.bat' ':app:testDebugUnitTest' '--no-daemon'
    Assert-LastExitCode 'Android JVM tests'
    & '.\gradlew.bat' ':app:assembleDebug' '--no-daemon'
    Assert-LastExitCode 'Android debug APK build'
}
finally {
    Set-Location -LiteralPath $projectRoot
    & subst.exe $driveRoot /D
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (
    Join-Path $projectRoot 'scripts\tests\test-mobile-apk-assets.ps1'
) -ApkPath (Join-Path $projectRoot 'mobile\android\app\build\outputs\apk\debug\app-debug.apk')
Assert-LastExitCode 'Android APK asset verification'

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'scripts\tests\test-mobile-release-signature.ps1')
Assert-LastExitCode 'Android release version/signature checks'

