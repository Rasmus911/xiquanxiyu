$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$project=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$wrapper=Join-Path $project 'scripts\invoke-operations-resume.ps1'
$stage='/opt/xiquan-releases/operations-stage-30e5e18e887c4a248226db43efacbc54'
$job='/opt/xiquan-backups/operations-cutover-dcfcd8852fe74c0db70233926f12e77b'
$receipt=$job+'/offline-image-ef2b95a0555444988f9ff2883877d0a2/verified-image.json'
function Assert([bool]$Value,[string]$Message) { if (-not $Value) { throw $Message } }
try {
    function global:ssh.exe { throw 'StageOnly attempted SSH' }
    function global:scp.exe { throw 'StageOnly attempted SCP' }
    & $wrapper -StageDirectory $stage -JobDirectory $job -ImageReceipt $receipt -StageOnly | Out-Null
    $refused=$false
    try { & $wrapper -StageDirectory $stage -JobDirectory $job -ImageReceipt ($job+'/../other/verified-image.json') -StageOnly | Out-Null } catch { $refused=$true }
    Assert $refused 'Cross-job receipt accepted'
    $global:XiquanResumeFixture=@{Uploads=@{};Resume=0;Apply=0;Tamper=$false;Answer='aaaaaaaa';WrongJob=$false;Failed=$false}
    function global:scp.exe {
        $local=[string]$args[-2]; $remote=([string]$args[-1]).Split(':',2)[1]
        $global:XiquanResumeFixture.Uploads[$remote]=(Get-FileHash -LiteralPath $local).Hash.ToLowerInvariant()
        $global:LASTEXITCODE=0
    }
    function global:ssh.exe {
        $command=[string]$args[-1]; $global:LASTEXITCODE=0
        if ($command.StartsWith('umask 077 && mkdir -m 700 ')) { return }
        if ($command.StartsWith('sha256sum ')) {
            foreach ($path in $command.Split(' ') | Select-Object -Skip 1) {
                $sha=$global:XiquanResumeFixture.Uploads[$path]
                if ($global:XiquanResumeFixture.Tamper) { $sha='0'*64 }
                Write-Output ($sha+'  '+$path)
            }
            return
        }
        if ($command -match '/operations_preview_recovery.py --mode prepare ') {
            $global:XiquanResumeFixture.Resume++
            Write-Output ('DEPLOY_PREVIEW_READY_JSON='+(@{job_path='/opt/xiquan-backups/operations-cutover-dcfcd8852fe74c0db70233926f12e77b';
                stage='/opt/xiquan-releases/operations-stage-30e5e18e887c4a248226db43efacbc54';preview_sha256=('a'*64);
                status='preview_ready';active_wristbands=100;formal_items=42;retained_money_and_history=$true} | ConvertTo-Json -Compress))
            return
        }
        if ($command -match '/operations_preview_recovery.py --mode apply .* --preview-sha256 a{64}$') {
            $global:XiquanResumeFixture.Apply++
            Write-Output 'OPERATIONS_CLOUD_DEPLOYED_OK'; return
        }
        if ($command -match '/operations_resume.py --stage /opt/xiquan-releases/operations-stage-30e5e18e887c4a248226db43efacbc54 --job /opt/xiquan-backups/operations-cutover-dcfcd8852fe74c0db70233926f12e77b --image-receipt /opt/xiquan-backups/operations-cutover-dcfcd8852fe74c0db70233926f12e77b/offline-image-ef2b95a0555444988f9ff2883877d0a2/verified-image.json$') {
            $global:XiquanResumeFixture.Resume++
            if ($global:XiquanResumeFixture.Failed) { $global:LASTEXITCODE=1; return }
            $prepared=@{job_path='/opt/xiquan-backups/operations-cutover-dcfcd8852fe74c0db70233926f12e77b';
                stage='/opt/xiquan-releases/operations-stage-30e5e18e887c4a248226db43efacbc54';preview_sha256=('a'*64);
                status='preview_ready';active_wristbands=100;formal_items=42;retained_money_and_history=$true}
            if ($global:XiquanResumeFixture.WrongJob) { $prepared.job_path='/opt/xiquan-backups/operations-cutover-'+('0'*32) }
            Write-Output ('DEPLOY_PREVIEW_READY_JSON='+($prepared | ConvertTo-Json -Compress)); return
        }
        if ($command -match '/operations_deploy.py --mode apply --stage /opt/xiquan-releases/operations-stage-30e5e18e887c4a248226db43efacbc54 --job /opt/xiquan-backups/operations-cutover-dcfcd8852fe74c0db70233926f12e77b --preview-sha256 a{64}$') {
            $global:XiquanResumeFixture.Apply++
            Write-Output 'OPERATIONS_CLOUD_DEPLOYED_OK'; return
        }
        throw 'Unexpected operation: rebuild or another job must never be invoked'
    }
    function global:Read-Host { return $global:XiquanResumeFixture.Answer }
    & $wrapper -StageDirectory $stage -JobDirectory $job -ImageReceipt $receipt -ApplyAfterPreview
    Assert ($global:XiquanResumeFixture.Resume -eq 1 -and $global:XiquanResumeFixture.Apply -eq 1) 'Confirmed resume flow failed'
    foreach ($case in @('Answer','WrongJob','Failed','Tamper')) {
        $global:XiquanResumeFixture.Answer='aaaaaaaa'; $global:XiquanResumeFixture.WrongJob=$false
        $global:XiquanResumeFixture.Failed=$false; $global:XiquanResumeFixture.Tamper=$false
        if ($case -eq 'Answer') { $global:XiquanResumeFixture.Answer='no' }
        else { $global:XiquanResumeFixture[$case]=$true }
        $before=$global:XiquanResumeFixture.Apply; $refused=$false
        try { & $wrapper -StageDirectory $stage -JobDirectory $job -ImageReceipt $receipt -ApplyAfterPreview | Out-Null } catch { $refused=$true }
        Assert ($refused -and $global:XiquanResumeFixture.Apply -eq $before) ('Unsafe apply occurred for '+$case)
    }
    $global:XiquanResumeFixture.Tamper=$false
    $global:XiquanResumeFixture.Failed=$false
    $global:XiquanResumeFixture.Answer='aaaaaaaa'
    $before=$global:XiquanResumeFixture.Apply
    & $wrapper -StageDirectory $stage -JobDirectory $job -ImageReceipt $receipt -Checkpoint Preview -ApplyAfterPreview
    Assert ($global:XiquanResumeFixture.Apply -eq $before+1) 'Preview checkpoint did not use the safe output driver for Apply'
    Write-Host 'OPERATIONS_RESUME_WRAPPER_TESTS_OK'
} finally {
    Remove-Item Function:\global:ssh.exe -ErrorAction SilentlyContinue
    Remove-Item Function:\global:scp.exe -ErrorAction SilentlyContinue
    Remove-Item Function:\global:Read-Host -ErrorAction SilentlyContinue
    Remove-Variable XiquanResumeFixture -Scope Global -ErrorAction SilentlyContinue
}
