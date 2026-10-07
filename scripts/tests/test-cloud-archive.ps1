$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression.FileSystem
$fixtureRoot = Join-Path ([IO.Path]::GetTempPath()) ('xiquan-archive-test-' + [guid]::NewGuid().ToString('N'))
$sourceRoot = Join-Path $fixtureRoot 'xiquan'
New-Item -ItemType Directory -Path $sourceRoot -Force | Out-Null
$sourceFile = Join-Path $sourceRoot 'installer.exe'
[IO.File]::WriteAllBytes($sourceFile, [Text.Encoding]::UTF8.GetBytes('test-only-installer-content'))
$hiddenFile = Join-Path $sourceRoot '.env.example'
[IO.File]::WriteAllBytes($hiddenFile, [Text.Encoding]::UTF8.GetBytes('PUBLIC_EXAMPLE=1'))
[IO.File]::SetAttributes($hiddenFile, [IO.FileAttributes]::Hidden)
$readLock = $null
try {
    $readLock = [IO.File]::Open($sourceFile, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $baselineRejected = $false
    try { Compress-Archive -LiteralPath $sourceRoot -DestinationPath (Join-Path $fixtureRoot 'baseline.zip') -ErrorAction Stop }
    catch { $baselineRejected = $true }
    if (-not $baselineRejected) { throw 'Expected Windows PowerShell Compress-Archive to reproduce the read-sharing conflict.' }
    Write-Host 'Reproduced: Windows PowerShell Compress-Archive rejects an existing shared-read handle.'

    . (Join-Path $PSScriptRoot '..\lib\cloud-archive.ps1')
    $zipPath = Join-Path $fixtureRoot 'shared-read.zip'
    New-CloudReleaseArchive -SourceDirectory $sourceRoot -DestinationPath $zipPath -MaximumAttempts 2 -RetryDelayMilliseconds 50
    $zip = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $entry = $zip.Entries | Where-Object { $_.FullName.Replace('\', '/') -eq 'xiquan/installer.exe' } | Select-Object -First 1
        if (-not $entry) { throw 'Archive must preserve the xiquan root directory.' }
        $reader = New-Object IO.StreamReader($entry.Open())
        try { if ($reader.ReadToEnd() -ne 'test-only-installer-content') { throw 'Installer contents changed.' } }
        finally { $reader.Dispose() }
        if (-not ($zip.Entries | Where-Object { $_.FullName.Replace('\', '/') -eq 'xiquan/.env.example' })) { throw 'Hidden public example files must not be silently omitted.' }
    }
    finally { $zip.Dispose() }
    $readLock.Dispose(); $readLock = $null

    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Threading;
public sealed class XiquanTimedArchiveFileLock : IDisposable {
    private FileStream stream;
    private Timer timer;
    public XiquanTimedArchiveFileLock(string path, int milliseconds) {
        stream = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.None);
        timer = new Timer(state => Release(), null, milliseconds, Timeout.Infinite);
    }
    private void Release() { var handle = Interlocked.Exchange(ref stream, null); if (handle != null) handle.Dispose(); }
    public void Dispose() { Release(); if (timer != null) timer.Dispose(); }
}
'@
    $temporaryLock = New-Object XiquanTimedArchiveFileLock($sourceFile, 500)
    try { New-CloudReleaseArchive -SourceDirectory $sourceRoot -DestinationPath (Join-Path $fixtureRoot 'retry.zip') -MaximumAttempts 15 -RetryDelayMilliseconds 100 }
    finally { $temporaryLock.Dispose() }
    if (-not (Test-Path -LiteralPath (Join-Path $fixtureRoot 'retry.zip'))) { throw 'Temporary locks should be retried successfully.' }

    $persistentLock = [IO.File]::Open($sourceFile, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::None)
    $failedZip = Join-Path $fixtureRoot 'must-not-publish.zip'
    $rejected = $false
    try { New-CloudReleaseArchive -SourceDirectory $sourceRoot -DestinationPath $failedZip -MaximumAttempts 2 -RetryDelayMilliseconds 10 }
    catch { $rejected = $true }
    finally { $persistentLock.Dispose() }
    if (-not $rejected -or (Test-Path -LiteralPath $failedZip)) { throw 'A persistent lock must fail without publishing a partial ZIP.' }
    if (@(Get-ChildItem -LiteralPath $fixtureRoot -Filter '*.partial' -File).Count) { throw 'Partial ZIP files were not cleaned up.' }
    Write-Host '5 cloud archive checks passed: shared-read, content/root, hidden file, temporary lock, persistent lock/partial cleanup.'
}
finally {
    if ($readLock) { $readLock.Dispose() }
    $resolvedFixture = [IO.Path]::GetFullPath($fixtureRoot)
    $resolvedTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolvedFixture.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase)) { throw 'Refusing fixture cleanup outside TEMP.' }
    Remove-Item -LiteralPath $resolvedFixture -Recurse -Force
}
