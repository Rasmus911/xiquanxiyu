[CmdletBinding()]
param([string]$PrivateKeyPath)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$delivery=Get-Content -LiteralPath (Join-Path $PSScriptRoot '交付信息.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$confirmation=Read-Host 'Confirm cloud step succeeded and existing data/accounts verified. Type PUBLISH 0.4.9'
if($confirmation-cne 'PUBLISH 0.4.9'){throw 'Publication cancelled. No signing/upload performed.'}
if(-not $PrivateKeyPath){
    $defaultPrivateKeyPath=Join-Path $delivery.ProjectRoot 'private\溪泉发布密钥\desktop-release-private.pem'
    $PrivateKeyPath=Read-Host ('Original desktop release private key path (blank: ' + $defaultPrivateKeyPath + ')')
    if(-not $PrivateKeyPath){$PrivateKeyPath=$defaultPrivateKeyPath}
}
$targets=@('win10-x86','win10-x64','win11-x86','win11-x64')
& (Join-Path $delivery.ProjectRoot 'scripts\sign-desktop-049.ps1') -ReleaseRoot $delivery.ReleaseRoot -PrivateKeyPath $PrivateKeyPath
& (Join-Path $delivery.ProjectRoot 'scripts\publish-windows-release.ps1') -ReleaseRoot $delivery.ReleaseRoot -Targets $targets
