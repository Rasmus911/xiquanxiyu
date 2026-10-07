[CmdletBinding()]
param([Parameter(Mandatory)][string]$PrivateKeyPath, [Parameter(Mandatory)][string]$PublicKeyPath)
$ErrorActionPreference = 'Stop'
if ((Test-Path -LiteralPath $PrivateKeyPath) -or (Test-Path -LiteralPath $PublicKeyPath)) { throw 'Existing keys will not be overwritten.' }
$password = Read-Host 'New release-key password (16+ characters, hidden)' -AsSecureString
$repeat = Read-Host 'Repeat password (hidden)' -AsSecureString
$firstPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
$secondPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($repeat)
$previousEncoding = $OutputEncoding
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($firstPtr)
    if ($plain.Length -lt 16 -or $plain -cne [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secondPtr)) { throw 'Passwords must match and have at least 16 characters.' }
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    @{action='new-key';privatePath=[IO.Path]::GetFullPath($PrivateKeyPath);publicPath=[IO.Path]::GetFullPath($PublicKeyPath);passphrase=$plain} |
        ConvertTo-Json -Compress | & node.exe (Join-Path $PSScriptRoot 'lib\desktop-signing.cjs')
    if ($LASTEXITCODE -ne 0) { throw 'Key creation failed.' }
} finally {
    $plain = $null; $OutputEncoding = $previousEncoding
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($firstPtr); [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secondPtr)
    $password.Dispose(); $repeat.Dispose()
}
