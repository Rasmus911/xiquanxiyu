Set-StrictMode -Version Latest

function Assert-SecurityReleaseBundle {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$Path)

    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    $archive = [IO.Compression.ZipFile]::OpenRead($resolved)
    try {
        $entries = @{}
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName.Replace('\', '/')
            if (-not $name.StartsWith('xiquan/', [StringComparison]::Ordinal) -or
                $name -match '(^|/)\.\.?(/|$)' -or $name.Contains(':') -or
                $name -match '(?i)(^|/)(private|node_modules|\.venv)(/|$)' -or
                $name -match '(?i)(^|/)\.env$|\.(jks|keystore|pem|key)$') {
                throw "Unsafe or private archive entry: $name"
            }
            if ((($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) { throw "Archive symlinks are not allowed: $name" }
            if ($entries.ContainsKey($name)) { throw "Duplicate archive entry: $name" }
            $entries[$name] = $entry
        }
        function Read-EntryText([string]$Name) {
            if (-not $entries.ContainsKey($Name)) { throw "Required release file missing: $Name" }
            $reader = New-Object IO.StreamReader($entries[$Name].Open(), [Text.Encoding]::UTF8)
            try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
        }
        function Get-EntryHash([string]$Name) {
            if (-not $entries.ContainsKey($Name)) { throw "Required release file missing: $Name" }
            $stream = $entries[$Name].Open()
            $sha = [Security.Cryptography.SHA256]::Create()
            try { return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
            finally { $sha.Dispose(); $stream.Dispose() }
        }
        $cloudPrefix = 'xiquan/deploy/cloud/'
        foreach ($required in @(
            'xiquan/server/Dockerfile', 'xiquan/server/app/__init__.py',
            'xiquan/server/migrations/versions/20260930_security_evidence.py',
            ($cloudPrefix + 'docker-compose.prod.yml'), ($cloudPrefix + 'scripts/runtime-role.sql'),
            ($cloudPrefix + 'scripts/common.sh'), ($cloudPrefix + 'web/index.html'),
            ($cloudPrefix + 'mobile/index.html'),
            ($cloudPrefix + 'updates/Xiquan-Bathhouse-Setup-0.4.0.exe.blockmap')
        )) {
            if (-not $entries.ContainsKey($required)) { throw "Required release file missing: $required" }
        }
        $policy = Read-EntryText ($cloudPrefix + 'releases/client-policy.json') | ConvertFrom-Json
        $mobile = Read-EntryText ($cloudPrefix + 'mobile/download-config.json') | ConvertFrom-Json
        $web = Read-EntryText ($cloudPrefix + 'web/version.json') | ConvertFrom-Json
        $manifest = Read-EntryText ($cloudPrefix + 'updates/latest.yml')
        if ([int]$policy.schemaVersion -ne 1 -or [string]$policy.desktop.latestVersion -ne '0.4.0' -or
            [string]$policy.desktop.minimumVersion -ne '0.4.0' -or
            $manifest -notmatch '(?m)^version:\s*0\.4\.0\s*$' -or
            $manifest -notmatch '(?m)^path:\s*Xiquan-Bathhouse-Setup-0\.4\.0\.exe\s*$') {
            throw 'The desktop policy and installer manifest must target 0.4.0.'
        }
        if ([string]$policy.android.latestVersion -ne '1.2.0' -or [string]$mobile.version -ne '1.2.0' -or
            [int]$policy.android.latestVersionCode -ne 7 -or [int]$mobile.versionCode -ne 7 -or
            [int]$policy.android.minimumVersionCode -ne 7 -or [int]$mobile.minimumVersionCode -ne 7) {
            throw 'The signed mobile release must be 1.2.0/code 7/minimum 7. Do not upload a SkipSignedMobile bundle.'
        }
        if ([string]$web.buildId -ne '20260930-security-040' -or [string]$policy.web.buildId -ne [string]$web.buildId) {
            throw 'The web build and release policy do not match the security upgrade.'
        }
        if ([string]$policy.desktop.downloadUrl -ne 'https://api.pqxqxy.xyz/updates/Xiquan-Bathhouse-Setup-0.4.0.exe' -or
            [string]$policy.android.downloadUrl -ne 'https://api.pqxqxy.xyz/mobile/downloads/xiquan-mobile-ordering-1.2.0.apk' -or
            [string]$mobile.androidApkUrl -ne '/mobile/downloads/xiquan-mobile-ordering-1.2.0.apk') {
            throw 'Download URLs do not match the configured bathhouse domain and release files.'
        }
        $exeHash = Get-EntryHash ($cloudPrefix + 'updates/Xiquan-Bathhouse-Setup-0.4.0.exe')
        $apkHash = Get-EntryHash ($cloudPrefix + 'mobile/downloads/xiquan-mobile-ordering-1.2.0.apk')
        if ($exeHash -ne [string]$policy.desktop.sha256 -or $apkHash -ne [string]$policy.android.sha256 -or
            $apkHash -ne [string]$mobile.sha256) { throw 'Installer/APK bytes do not match their SHA256 manifests.' }
        return [pscustomobject]@{
            Path = $resolved; DesktopVersion = '0.4.0'; MobileVersion = '1.2.0'; WebBuildId = [string]$web.buildId
            DesktopSha256 = $exeHash; MobileSha256 = $apkHash
        }
    }
    finally { $archive.Dispose() }
}
