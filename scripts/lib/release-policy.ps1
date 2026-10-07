Set-StrictMode -Version Latest

function Test-XiquanSemanticVersion {
    param([AllowNull()][object]$Value)

    return [string]$Value -match '^\d+\.\d+\.\d+$'
}

function Test-XiquanHttpsUrl {
    param([AllowNull()][object]$Value)

    try {
        $uri = [Uri][string]$Value
        return $uri.IsAbsoluteUri -and
            $uri.Scheme -eq 'https' -and
            -not $uri.UserInfo
    }
    catch {
        return $false
    }
}

function Assert-XiquanReleasePolicyEntry {
    param(
        [Parameter(Mandatory)][ValidateSet('desktop', 'android', 'web')][string]$Platform,
        [Parameter(Mandatory)][hashtable]$Release
    )

    if (-not $Release.ContainsKey('required')) {
        throw 'Release entry must include required.'
    }
    if (-not $Release.ContainsKey('releaseNotes') -or $Release.releaseNotes -is [string]) {
        throw 'releaseNotes must be an array.'
    }
    if (-not $Release.ContainsKey('publishedAt') -or -not [string]$Release.publishedAt) {
        throw 'Release entry must include publishedAt.'
    }

    if ($Platform -eq 'web') {
        if (-not $Release.ContainsKey('buildId') -or -not [string]$Release.buildId) {
            throw 'Web release must include buildId.'
        }
        return
    }

    if (-not (Test-XiquanSemanticVersion $Release.latestVersion)) {
        throw 'latestVersion must use x.y.z format.'
    }
    if (-not (Test-XiquanHttpsUrl $Release.downloadUrl)) {
        throw 'downloadUrl must be an absolute HTTPS URL.'
    }
    if ([string]$Release.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw 'sha256 must be 64 lowercase hexadecimal characters.'
    }

    if ($Platform -eq 'desktop') {
        if (-not (Test-XiquanSemanticVersion $Release.minimumVersion)) {
            throw 'minimumVersion must use x.y.z format.'
        }
        return
    }

    $latestCode = 0
    $minimumCode = 0
    if (-not [int]::TryParse([string]$Release.latestVersionCode, [ref]$latestCode) -or $latestCode -lt 1) {
        throw 'latestVersionCode must be a positive integer.'
    }
    if (-not [int]::TryParse([string]$Release.minimumVersionCode, [ref]$minimumCode) -or $minimumCode -lt 1) {
        throw 'minimumVersionCode must be a positive integer.'
    }
    if ($minimumCode -gt $latestCode) {
        throw 'minimumVersionCode cannot exceed latestVersionCode.'
    }
}

function Update-ClientReleasePolicy {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][ValidateSet('desktop', 'android', 'web')][string]$Platform,
        [Parameter(Mandatory)][hashtable]$Release
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Release policy not found: $Path"
    }

    Assert-XiquanReleasePolicyEntry -Platform $Platform -Release $Release

    $policy = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ([int]$policy.schemaVersion -ne 1) {
        throw 'Unsupported release policy schema.'
    }
    foreach ($requiredPlatform in @('desktop', 'android', 'web')) {
        if (-not $policy.PSObject.Properties[$requiredPlatform]) {
            throw "Release policy is missing $requiredPlatform."
        }
    }

    $policy.$Platform = [pscustomobject]$Release
    $temporary = "$Path.new"
    try {
        $json = $policy | ConvertTo-Json -Depth 10
        $utf8 = New-Object System.Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, $utf8)
        [IO.File]::ReadAllText($temporary, [Text.Encoding]::UTF8) | ConvertFrom-Json | Out-Null
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}
