[CmdletBinding()]
param([Parameter(Mandatory)][string]$ApkPath,[Parameter(Mandatory)][string]$PreviousApkPath)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'mobile-release-signature.ps1')
$previousHash = (Get-FileHash -LiteralPath $PreviousApkPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($previousHash -ne '869e52d5d76265591ff7936f27706eacbb690df5afb7952a11b128eeba6af04c') { throw 'Known original Android 1.2.2/code9 hash mismatch.' }
$result = Assert-SignedMobileRelease -ApkPath $ApkPath -PreviousApkPath $PreviousApkPath -ExpectedVersion '1.2.3' -ExpectedVersionCode 10
if ($result.CertificateSha256 -ne '15257f00ccafcabfbac7c105b3a4606127f4d04afa55e44994171994a1ce50e9') { throw 'Original Android signer mismatch.' }
$result | ConvertTo-Json -Compress
