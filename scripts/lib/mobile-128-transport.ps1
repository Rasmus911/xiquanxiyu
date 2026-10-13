Set-StrictMode -Version Latest

function ConvertTo-TokenNativeArgument([string]$Value) {
    $quoted = [regex]::Replace($Value, '(\\*)"', {
        param($match)
        $match.Groups[1].Value + $match.Groups[1].Value + '\"'
    })
    $quoted = [regex]::Replace($quoted, '(\\+)$', {
        param($match)
        $match.Value + $match.Value
    })
    return '"' + $quoted + '"'
}

function Invoke-TokenNative {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string[]]$Arguments,
        [ValidateRange(1,600)][int]$TimeoutSeconds = 90,
        [string]$InputText = '',
        [string]$Label = 'SSH'
    )
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.Arguments = ($Arguments | ForEach-Object { ConvertTo-TokenNativeArgument $_ }) -join ' '
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $info.StandardOutputEncoding = $utf8
    $info.StandardErrorEncoding = $utf8
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $nextNotice = 15
    $started = $false
    try {
        [void]$process.Start()
        $started = $true
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $writing = $process.StandardInput.WriteAsync($InputText)
        $inputClosed = $false
        while (-not $process.HasExited -or -not $stdout.IsCompleted -or -not $stderr.IsCompleted) {
            if (-not $inputClosed -and $writing.IsCompleted) {
                [void]$writing.GetAwaiter().GetResult()
                $process.StandardInput.Close()
                $inputClosed = $true
            }
            if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
                if (-not $process.HasExited) { $process.Kill(); [void]$process.WaitForExit(2000) }
                throw ('TOKEN_TRANSPORT_TIMEOUT: ' + $Label + ' exceeded ' + $TimeoutSeconds + 's. Stopped; no automatic retry.')
            }
            if ($timer.Elapsed.TotalSeconds -ge $nextNotice) {
                Write-Host ('TRANSPORT_WAIT: ' + $Label + ' ' + [int]$timer.Elapsed.TotalSeconds + '/' + $TimeoutSeconds + 's')
                $nextNotice += 15
            }
            [void]$process.WaitForExit(100)
        }
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            Stdout = $stdout.GetAwaiter().GetResult()
            Stderr = $stderr.GetAwaiter().GetResult()
        }
    } finally {
        if ($started -and -not $process.HasExited) { $process.Kill() }
        $process.Dispose()
        $timer.Stop()
    }
}

function New-TokenUploadProgram {
    param([Parameter(Mandatory)][string]$LocalPath, [Parameter(Mandatory)][string]$RemotePath)
    if ($RemotePath -notmatch '^/tmp/xiquan-(token128|android128)-[0-9a-f]{32}/(patch\.py|mobile\.py|publish\.py|config\.json|app\.apk|web\.zip)$') {
        throw 'Invalid upload destination; nothing transferred.'
    }
    $file = Get-Item -LiteralPath $LocalPath
    if ($file.PSIsContainer -or $file.Length -gt 64MB) { throw 'Unexpected upload input size/type.' }
    $bytes = [IO.File]::ReadAllBytes($file.FullName)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { $digest = ([BitConverter]::ToString($algorithm.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose() }
    $encoded = [Convert]::ToBase64String($bytes)
    return @"
import base64, hashlib, os, uuid
from pathlib import Path
p = Path('$RemotePath')
if any(v.is_symlink() for v in (p, *p.parents)) or not p.parent.is_dir():
    raise SystemExit('UPLOAD_PATH_INVALID')
data = base64.b64decode('$encoded', validate=True)
if hashlib.sha256(data).hexdigest() != '$digest':
    raise SystemExit('UPLOAD_HASH_INVALID')
temporary = p.with_name('.upload128-' + uuid.uuid4().hex)
with temporary.open('xb') as stream:
    stream.write(data)
    stream.flush()
    os.fsync(stream.fileno())
temporary.chmod(0o600)
os.replace(temporary, p)
if hashlib.sha256(p.read_bytes()).hexdigest() != '$digest':
    raise SystemExit('UPLOAD_FILE_HASH_INVALID')
print('UPLOAD_VERIFIED $digest $RemotePath', flush=True)
"@
}
