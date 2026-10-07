$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'mobile-asset-policy.ps1')

$csp = '<meta http-equiv="Content-Security-Policy" content="connect-src https: http://127.0.0.1:* ws://localhost:*">'
if (Test-MobileDevelopmentUrl -Content $csp -IsIndexHtml) { throw 'Loopback CSP permissions are not a configured development server.' }
if (-not (Test-MobileDevelopmentUrl -Content ($csp + '<script src="http://127.0.0.1:5174/main.js"></script>') -IsIndexHtml)) {
    throw 'A development script URL must still be rejected.'
}
if (-not (Test-MobileDevelopmentUrl -Content 'const api="http://127.0.0.1:5001/api";')) {
    throw 'A bundled local API endpoint must still be rejected.'
}
if (-not (Test-MobileDevelopmentUrl -Content 'const server="http://localhost:5174";')) {
    throw 'The development mobile server must still be rejected.'
}
Write-Host 'Mobile asset URL policy tests passed.' -ForegroundColor Green
