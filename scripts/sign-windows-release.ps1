[CmdletBinding()]
param([Parameter(Mandatory)][string]$ReleaseRoot, [Parameter(Mandatory)][string]$PrivateKeyPath,
    [Parameter(Mandatory)][ValidateRange(1,2147483647)][int]$Sequence,
    [string]$MinimumVersion = '0.4.2', [string[]]$ReleaseNotes = @('Windows compatibility update'), [switch]$Required,
    [ValidateSet('win7-x86','win7-x64','win10-x86','win10-x64','win11-x86','win11-x64')]
    [string[]]$Targets = @('win7-x86','win7-x64','win10-x86','win10-x64','win11-x86','win11-x64'))
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $ReleaseRoot -ErrorAction Stop).Path
$keyPath = (Resolve-Path -LiteralPath $PrivateKeyPath -ErrorAction Stop).Path
if ($keyPath.StartsWith($root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Private keys must stay outside the release folder.' }
$password = Read-Host 'Release-key password (hidden)' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
$previousEncoding = $OutputEncoding
try {
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    @{action='sign';releaseRoot=$root;privatePath=$keyPath;passphrase=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer);
        sequence=$Sequence;minimumVersion=$MinimumVersion;releaseNotes=@($ReleaseNotes);required=[bool]$Required;targets=@($Targets)} |
        ConvertTo-Json -Depth 5 -Compress | & node.exe (Join-Path $PSScriptRoot 'lib\desktop-signing.cjs')
    if ($LASTEXITCODE -ne 0) { throw 'Release signing failed. Nothing was uploaded.' }
} finally {
    $OutputEncoding = $previousEncoding
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $password.Dispose()
}
