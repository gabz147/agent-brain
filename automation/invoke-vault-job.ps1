# Shared scheduled runner. Guard behavior and Interactive/hidden task identity remain intact.
param(
    [ValidateSet('drain','audit')][string]$Kind,
    [switch]$DryRun,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$ScriptDir = $PSScriptRoot
$Ctl = Join-Path $ScriptDir 'vaultctl.py'
$LogPath = Join-Path $ScriptDir ($Kind + '.log')
$StampPath = Join-Path $ScriptDir 'last-audit-date.txt'
$LegacyLockPath = Join-Path $ScriptDir '.drain.lock'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$LegacyLock = $null
$PythonPath = $null
$PriorEncoding = $env:PYTHONIOENCODING
$PriorAutomation = $env:VAULT_AUTOMATION

function Write-JobLog {
    param([string]$Message)
    Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ('[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $Message)
}
function Defer-Job {
    param([string]$Reason)
    $line = Update-DeferralStreak -Name $Kind -Reason $Reason
    if ($null -ne $line) { Write-JobLog $line }
}
try {
    . (Join-Path $ScriptDir 'user-busy.ps1')
    $PythonCommand = if ($env:BRAIN_PYTHON) { $env:BRAIN_PYTHON } else { 'python.exe' }
    $PythonPath = (Get-Command $PythonCommand -ErrorAction Stop).Source
    if (-not (Test-Path -LiteralPath $Ctl)) { throw 'Shared vault controller is missing' }
    if ($DryRun) {
        Write-Output (@{ kind=$Kind; mode='dry-run'; controller=$Ctl; operation=$(if ($Kind -eq 'audit') {'hygiene --fix'} else {'drain'}); model_calls=$(if ($Kind -eq 'audit') {0} else {'only uncovered source evidence'}) } | ConvertTo-Json -Compress)
        exit 0
    }
    $pause = Get-AutomationPause -Scope 'afk'
    if ($null -ne $pause) { Defer-Job $pause; exit 0 }
    $busy = Get-UserBusyReason
    if ($null -ne $busy) { Defer-Job $busy; exit 0 }
    $today = (Get-Date).ToString('yyyy-MM-dd')
    if (($Kind -eq 'audit') -and (-not $Force) -and (Test-Path -LiteralPath $StampPath)) {
        if ([System.IO.File]::ReadAllText($StampPath).Trim() -eq $today) {
            Defer-Job 'already audited today'
            exit 0
        }
    }
    # Preserve the existing FileShare::None activity signal used by both
    # Obsidian plugins; this also serializes against a pre-upgrade runner.
    try {
        $LegacyLock = [System.IO.File]::Open($LegacyLockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        $LegacyLock.SetLength(0)
        $bytes = $Utf8NoBom.GetBytes([string]$PID)
        $LegacyLock.Write($bytes,0,$bytes.Length)
        $LegacyLock.Flush($true)
    } catch {
        Defer-Job 'drain in progress'
        exit 0
    }
    $streak = Close-DeferralStreak -Name $Kind
    if ($null -ne $streak) { Write-JobLog $streak }
    Write-JobLog ('START ' + $Kind + ' through shared controller')
    $env:PYTHONIOENCODING = 'utf-8'
    $env:VAULT_AUTOMATION = '1'
    if ($Kind -eq 'audit') {
        $output = & $PythonPath $Ctl hygiene --fix
    } else {
        $output = & $PythonPath $Ctl drain --directory $ScriptDir --max-attempts 8
    }
    $code = $LASTEXITCODE
    $result = (($output | ForEach-Object { [string]$_ }) -join "`n") | ConvertFrom-Json -ErrorAction Stop
    if (($code -ne 0) -and ($result.outcome -eq 'failed')) {
        $null = & $PythonPath $Ctl report-error --kind $Kind --error ([string]$result.error)
    }
    if ($Kind -eq 'audit') {
        if (($code -eq 0) -and ($result.outcome -eq 'verified')) {
            $tempStamp = $StampPath + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
            [System.IO.File]::WriteAllText($tempStamp,$today,$Utf8NoBom)
            Move-Item -LiteralPath $tempStamp -Destination $StampPath -Force -ErrorAction Stop
            Write-JobLog ('verified: ' + $result.notes + ' notes; ' + $result.repairs.Count + ' repairs; no model calls')
        } else {
            Write-JobLog ('NOT stamped: outcome=' + $result.outcome + '; issues=' + $result.issues.Count + '; controller exit=' + $code)
        }
    } else {
        Write-JobLog ('result: ' + ($result | ConvertTo-Json -Compress -Depth 5))
        if (($code -eq 0) -and ($result.completed -gt 0)) {
            Write-JobLog ('[INFO] verified ' + $result.completed + ' source records with durable receipts')
        }
    }
    Write-JobLog ('END ' + $Kind + ' (controller exit=' + $code + ')')
    exit 0
} catch {
    $message = $_.Exception.Message
    Write-JobLog ('ERROR ' + $message)
    if ($null -ne $PythonPath) {
        try { $null = & $PythonPath $Ctl report-error --kind $Kind --error $message } catch { }
    }
    # Scheduled failures remain visible in logs/receipts but never block a
    # real interactive session or produce a task error storm.
    exit 0
} finally {
    $env:PYTHONIOENCODING = $PriorEncoding
    $env:VAULT_AUTOMATION = $PriorAutomation
    if ($null -ne $LegacyLock) {
        $LegacyLock.Dispose()
        try { Remove-Item -LiteralPath $LegacyLockPath -Force -ErrorAction Stop } catch { }
    }
}
