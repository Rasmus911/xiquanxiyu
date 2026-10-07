Set-StrictMode -Version Latest

function New-CloudReleaseArchive {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$SourceDirectory,
        [Parameter(Mandatory)][string]$DestinationPath,
        [ValidateRange(1, 30)][int]$MaximumAttempts = 8,
        [ValidateRange(0, 5000)][int]$RetryDelayMilliseconds = 2000,
        [switch]$PortableEntryNames
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    Add-Type -AssemblyName System.IO.Compression
    $source = (Resolve-Path -LiteralPath $SourceDirectory -ErrorAction Stop).Path
    $destination = [IO.Path]::GetFullPath($DestinationPath)
    if (-not (Test-Path -LiteralPath $source -PathType Container)) { throw 'Archive source must be a directory.' }
    if (Test-Path -LiteralPath $destination) { throw "Refusing to overwrite an existing release: $destination" }
    $parent = [IO.Path]::GetDirectoryName($destination)
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw 'Archive destination parent directory is missing.' }
    $sourcePrefix = [IO.Path]::GetFullPath($source).TrimEnd('\') + '\'
    if ($destination.StartsWith($sourcePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Archive output must be outside its source directory.' }
    $partial = Join-Path $parent ('.xiquan-' + [guid]::NewGuid().ToString('N') + '.partial')
    try {
        for ($attempt = 1; $attempt -le $MaximumAttempts; $attempt++) {
            try {
                # Unlike Windows PowerShell Compress-Archive's exclusive file open,
                # .NET reads source files with FileShare.Read. Hidden files are included.
                if ($PortableEntryNames) {
                    # .NET Framework's CreateFromDirectory writes Windows backslashes.
                    # Source packages must pass the Linux extraction path preflight.
                    $portableStream = [IO.File]::Open($partial, [IO.FileMode]::CreateNew,
                        [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
                    try {
                        $portableArchive = [IO.Compression.ZipArchive]::new(
                            $portableStream, [IO.Compression.ZipArchiveMode]::Create, $true)
                        try {
                            $baseName = Split-Path -Leaf $source
                            foreach ($sourceFile in Get-ChildItem -LiteralPath $source -Recurse -File -Force) {
                                if ($sourceFile.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                                    throw 'Portable archive files must not be links.'
                                }
                                $relativeName = $sourceFile.FullName.Substring($sourcePrefix.Length).Replace('\', '/')
                                [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                                    $portableArchive, $sourceFile.FullName, ($baseName + '/' + $relativeName),
                                    [IO.Compression.CompressionLevel]::Optimal)
                            }
                        } finally { $portableArchive.Dispose() }
                    } finally { $portableStream.Dispose() }
                } else {
                    [IO.Compression.ZipFile]::CreateFromDirectory(
                        $source, $partial, [IO.Compression.CompressionLevel]::Optimal, $true)
                }
                # Publish only a completely closed, readable archive; never expose a partial ZIP.
                $archive = [IO.Compression.ZipFile]::OpenRead($partial)
                try { if ($archive.Entries.Count -lt 1) { throw 'Archive contains no entries.' } }
                finally { $archive.Dispose() }
                [IO.File]::Move($partial, $destination)
                return
            }
            catch {
                $cause = $_.Exception.GetBaseException()
                $isSharingConflict = $cause -is [IO.IOException] -and (($cause.HResult -band 0xFFFF) -in @(32, 33))
                if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force -ErrorAction Stop }
                if (-not $isSharingConflict -or $attempt -ge $MaximumAttempts) { throw }
                Write-Warning "Release file is temporarily in use; archive retry $($attempt + 1)/$MaximumAttempts. Security software remains enabled."
                Start-Sleep -Milliseconds $RetryDelayMilliseconds
            }
        }
    }
    finally {
        # This is only the uniquely named temporary file created above, never an old release.
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force -ErrorAction Stop }
    }
}
