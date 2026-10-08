param([string]$Directory = $PSScriptRoot)
$ErrorActionPreference = 'Stop'
$base = (Resolve-Path -LiteralPath $Directory).Path
$manifest = Get-Content -LiteralPath (Join-Path $base 'parts-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($installer in $manifest.installers) {
    if ($installer.name -notmatch '^[A-Za-z0-9._-]+\.exe$') { throw 'Unsafe installer filename' }
    $output = Join-Path $base $installer.name
    foreach ($part in $installer.parts) {
        if ($part.name -notmatch '^[A-Za-z0-9._-]+\.exe\.part[0-9]{3}$') { throw 'Unsafe part filename' }
        $input = Join-Path $base $part.name
        $item = Get-Item -LiteralPath $input
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Linked file not allowed' }
        if ($item.Length -ne $part.bytes) { throw ('Wrong file length: ' + $part.name) }
        if ((Get-FileHash -LiteralPath $input -Algorithm SHA256).Hash.ToLowerInvariant() -ne $part.sha256) { throw ('Hash mismatch: ' + $part.name) }
    }
    if (Test-Path -LiteralPath $output) {
        if ((Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant() -eq $installer.sha256) {
            Write-Host ('Already verified: ' + $output)
            continue
        }
        throw ('Refusing to overwrite existing file: ' + $output)
    }
    $destination = [IO.File]::Open($output, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        foreach ($part in $installer.parts) {
            $source = [IO.File]::OpenRead((Join-Path $base $part.name))
            try { $source.CopyTo($destination) } finally { $source.Dispose() }
        }
    } finally { $destination.Dispose() }
    if ((Get-Item -LiteralPath $output).Length -ne $installer.bytes) { throw 'Reassembled file length mismatch; do not run' }
    if ((Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant() -ne $installer.sha256) { throw 'Reassembled hash mismatch; do not run' }
    Write-Host ('Verified installer: ' + $output)
}
