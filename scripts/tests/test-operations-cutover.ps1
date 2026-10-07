$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$project=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$wrapper=Join-Path $project 'scripts\invoke-operations-cutover.ps1'
if (-not (Test-Path -LiteralPath $wrapper)) { throw 'Reviewed cloud cutover wrapper missing' }
function Assert([bool]$Value,[string]$Message) { if (-not $Value) { throw $Message } }
try {
    function global:ssh.exe { throw 'StageOnly attempted SSH' }
    function global:scp.exe { throw 'StageOnly attempted SCP' }
    & $wrapper -StageDirectory '/opt/xiquan-releases/operations-stage-30e5e18e887c4a248226db43efacbc54' -StageOnly | Out-Null
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $wrapper -StageDirectory '/opt/xiquan-releases/operations-stage-30e5e18e887c4a248226db43efacbc54' -StageOnly | Out-Null
    Assert ($LASTEXITCODE -eq 0) 'Windows PowerShell StageOnly failed'
    $refused=$false
    try { & $wrapper -StageDirectory '/opt/xiquan-releases/../outside' -StageOnly | Out-Null } catch { $refused=$true }
    Assert $refused 'Unsafe stage accepted'
    $global:XiquanCutoverFixture=[pscustomobject]@{Uploads=@{};Prepare=0;Apply=0;Tamper=$false;Answer='aaaaaaaa'}
    function global:scp.exe {
        $local=[string]$args[-2]; $remote=([string]$args[-1]).Split(':',2)[1]
        $global:XiquanCutoverFixture.Uploads[$remote]=(Get-FileHash -LiteralPath $local).Hash.ToLowerInvariant()
        $global:LASTEXITCODE=0
    }
    function global:ssh.exe {
        $command=[string]$args[-1]
        $global:LASTEXITCODE=0
        if ($command.StartsWith('umask 077 && mkdir -m 700 ')) { return }
        if ($command.StartsWith('sha256sum ')) {
            foreach ($path in $command.Split(' ') | Select-Object -Skip 1) {
                $sha=$global:XiquanCutoverFixture.Uploads[$path]
                if ($global:XiquanCutoverFixture.Tamper) { $sha='0'*64 }
                Write-Output ($sha+'  '+$path)
            }
            return
        }
        if ($command -match ' --mode prepare --stage /opt/xiquan-releases/operations-stage-[0-9a-f]{32}$') {
            $global:XiquanCutoverFixture.Prepare++
            Write-Output ('DEPLOY_PREVIEW_READY_JSON='+(@{job_path='/opt/xiquan-backups/operations-cutover-0123456789abcdef0123456789abcdef';preview_sha256=('a'*64);status='preview_ready'} | ConvertTo-Json -Compress))
            return
        }
        if ($command -match ' --mode apply --stage /opt/xiquan-releases/operations-stage-[0-9a-f]{32} --job /opt/xiquan-backups/operations-cutover-[0-9a-f]{32} --preview-sha256 a{64}$') {
            $global:XiquanCutoverFixture.Apply++
            Write-Output 'OPERATIONS_CLOUD_DEPLOYED_OK'; return
        }
        throw 'Unexpected cloud mutation'
    }
    function global:Read-Host { return $global:XiquanCutoverFixture.Answer }
    & $wrapper -StageDirectory '/opt/xiquan-releases/operations-stage-30e5e18e887c4a248226db43efacbc54' -ApplyAfterPreview
    Assert ($global:XiquanCutoverFixture.Prepare -eq 1 -and $global:XiquanCutoverFixture.Apply -eq 1) 'Confirmed flow failed'
    $global:XiquanCutoverFixture.Answer='no'
    $refused=$false
    try { & $wrapper -StageDirectory '/opt/xiquan-releases/operations-stage-30e5e18e887c4a248226db43efacbc54' -ApplyAfterPreview | Out-Null } catch { $refused=$true }
    Assert ($refused -and $global:XiquanCutoverFixture.Apply -eq 1) 'Unconfirmed preview was applied'
    $global:XiquanCutoverFixture.Tamper=$true
    $refused=$false
    try { & $wrapper -StageDirectory '/opt/xiquan-releases/operations-stage-30e5e18e887c4a248226db43efacbc54' -ApplyAfterPreview | Out-Null } catch { $refused=$true }
    Assert ($refused -and $global:XiquanCutoverFixture.Prepare -eq 2) 'Tampered uploaded driver was executed'
    Write-Host 'OPERATIONS_CUTOVER_WRAPPER_TESTS_OK'
} finally {
    Remove-Item Function:\global:ssh.exe -ErrorAction SilentlyContinue
    Remove-Item Function:\global:scp.exe -ErrorAction SilentlyContinue
    Remove-Item Function:\global:Read-Host -ErrorAction SilentlyContinue
    Remove-Variable XiquanCutoverFixture -Scope Global -ErrorAction SilentlyContinue
}
