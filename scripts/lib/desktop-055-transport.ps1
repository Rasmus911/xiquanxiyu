Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'mobile-128-transport.ps1')

function Invoke-Desktop055Operation {
    param(
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string[]]$Arguments,
        [ValidateRange(1,18000)][int]$TimeoutSeconds = 14430,
        [Parameter(Mandatory)][string]$IdentityFile,
        [ValidatePattern('^/opt/xiquan-releases/desktop055-stage-[0-9a-f]{32}$')][string]$Stage,
        [ValidatePattern('^(/opt/xiquan-backups/desktop055-cutover-[0-9a-f]{32})?$')][string]$Job = ''
    )
    $identity = [ordered]@{ Stage=$Stage; Job=$Job; Phase='transport-start'; TimedOut=$false; AutomaticRetry=$false }
    $lines = New-Object 'System.Collections.Generic.List[string]'
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $identityPath = [IO.Path]::GetFullPath($IdentityFile)
    if (-not [IO.Directory]::Exists([IO.Path]::GetDirectoryName($identityPath))) { throw 'Identity directory must exist.' }
    function Save-Desktop055Identity {
        $temporary = $identityPath + '.' + [guid]::NewGuid().ToString('N')
        [IO.File]::WriteAllText($temporary, ($identity | ConvertTo-Json -Compress), $utf8)
        if ([IO.File]::Exists($identityPath)) { [IO.File]::Replace($temporary,$identityPath,[System.Management.Automation.Language.NullString]::Value) }
        else { [IO.File]::Move($temporary,$identityPath) }
    }
    function Receive-Desktop055Line([string]$Line) {
        $safe = $false
        if ($Line -cmatch '^PRIVATE_DESKTOP_JOB=(/opt/xiquan-backups/desktop055-cutover-[0-9a-f]{32})$') {
            if ($identity.Job -and $identity.Job -cne $Matches[1]) { throw 'Cloud recovery identity changed; do not retry.' }
            $identity.Job=$Matches[1]; $safe=$true
        } elseif ($Line -cmatch '^PRIVATE_DESKTOP_STAGE=(/opt/xiquan-releases/desktop055-stage-[0-9a-f]{32})$') {
            if ($identity.Stage -cne $Matches[1]) { throw 'Cloud stage identity changed; do not retry.' }
            $safe=$true
        } elseif ($Line -cmatch '^DESKTOP055_PHASE=([a-z0-9-]+)$') {
            $identity.Phase=$Matches[1]; $safe=$true
        } elseif ($Line -cmatch '^DESKTOP055_STOPPED: phase=[a-z0-9-]+ category=[a-z0-9]+ evidence=/opt/xiquan-backups/desktop055-cutover-[0-9a-f]{32}/failure-[0-9a-f]{32}\.json$') {
            $safe=$true
        }
        if ($safe) { $lines.Add($Line); Save-Desktop055Identity; Write-Host $Line }
    }
    Save-Desktop055Identity
    Write-Host ('LOCAL_RECOVERY_IDENTITY=' + $identityPath)
    $info=New-Object Diagnostics.ProcessStartInfo
    $info.FileName=$Executable
    $info.Arguments=($Arguments | ForEach-Object { ConvertTo-TokenNativeArgument $_ }) -join ' '
    $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true; $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
    $info.StandardOutputEncoding=$utf8; $info.StandardErrorEncoding=$utf8
    $process=New-Object Diagnostics.Process
    $process.StartInfo=$info
    $timer=[Diagnostics.Stopwatch]::StartNew()
    $started=$false; $nextNotice=15
    try {
        [void]$process.Start(); $started=$true; $process.StandardInput.Close()
        $streams=@(
            @{Reader=$process.StandardOutput; Task=$process.StandardOutput.ReadLineAsync(); Done=$false},
            @{Reader=$process.StandardError; Task=$process.StandardError.ReadLineAsync(); Done=$false}
        )
        while (-not $process.HasExited -or @($streams | Where-Object { -not $_.Done }).Count) {
            foreach ($stream in $streams) {
                if (-not $stream.Done -and $stream.Task.IsCompleted) {
                    $line=$stream.Task.GetAwaiter().GetResult()
                    if ($null -eq $line) { $stream.Done=$true }
                    else { Receive-Desktop055Line $line; $stream.Task=$stream.Reader.ReadLineAsync() }
                }
            }
            if ($timer.Elapsed.TotalSeconds -ge $TimeoutSeconds) {
                $identity.TimedOut=$true; Save-Desktop055Identity
                if (-not $process.HasExited) { $process.Kill(); [void]$process.WaitForExit(2000) }
                Write-Host ('DESKTOP055_TRANSPORT_TIMEOUT: retained ' + $identityPath + '; no automatic retry')
                return [pscustomobject]@{ExitCode=124;Stdout=($lines -join "`n");Stderr='';TimedOut=$true;IdentityFile=$identityPath}
            }
            if ($timer.Elapsed.TotalSeconds -ge $nextNotice) {
                Write-Host ('TRANSPORT_WAIT: DESKTOP055 ' + [int]$timer.Elapsed.TotalSeconds + '/' + $TimeoutSeconds + 's phase=' + $identity.Phase)
                $nextNotice+=15
            }
            [void]$process.WaitForExit(50)
        }
        return [pscustomobject]@{ExitCode=$process.ExitCode;Stdout=($lines -join "`n");Stderr='';TimedOut=$false;IdentityFile=$identityPath}
    } finally {
        Save-Desktop055Identity
        if ($started -and -not $process.HasExited) { $process.Kill() }
        $process.Dispose(); $timer.Stop()
    }
}
