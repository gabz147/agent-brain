<#
.SYNOPSIS
    Nightly Obsidian vault audit runner. Invokes `claude -p` headlessly against
    audit-prompt.md with VAULT_AUTOMATION=1 set, so the audit's own session
    does not re-queue itself (loop guard).

.DESCRIPTION
    Windows PowerShell 5.1 compatible. Always exits 0 so a failed audit does
    not surface as a scheduled-task error storm; failures are logged instead.

    PORTABILITY: locates its own directory via $MyInvocation, so it runs from
    wherever you place the automation folder. The vault root is read from
    BRAIN_VAULT_ROOT (fallback ~/Documents/Brain) and injected into the audit
    prompt in place of {{VAULT_ROOT}}.

.PARAMETER DryRun
    Skip the actual `claude -p` call. Log what would have run and exit 0.
#>
param(
    [switch]$DryRun,
    # Bypass the once-per-day stamp and the user-presence guard. For manual runs.
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$PromptPath   = Join-Path $ScriptDir 'audit-prompt.md'
$LogPath      = Join-Path $ScriptDir 'audit.log'
$LockPath     = Join-Path $ScriptDir '.drain.lock'
$StampPath    = Join-Path $ScriptDir 'last-audit-date.txt'
$BusyGuardPath = Join-Path $ScriptDir 'user-busy.ps1'

$VaultRoot    = if ($env:BRAIN_VAULT_ROOT) { $env:BRAIN_VAULT_ROOT } else { Join-Path $env:USERPROFILE 'Documents\Brain' }

# Shared guard: never run while the user is at the machine (see user-busy.ps1).
if (Test-Path -LiteralPath $BusyGuardPath) {
    . $BusyGuardPath
}

# How far back the audit may reach when the machine has been off for a while.
$MaxLookbackDays = 7

$Utf8NoBom    = New-Object System.Text.UTF8Encoding($false)

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$timestamp] $Message"
    Add-Content -Path $LogPath -Value $line -Encoding utf8
}

function Get-VaultLock {
    # Same lockfile and same CreateNew / FileShare::None pattern as
    # Get-DrainLock in drain-queue.ps1: the audit and a drain both do
    # read-modify-write passes over the same vault notes, so they must never
    # run concurrently. Returns an open FileStream, or $null if held.
    #
    # The holder keeps the file open exclusively for its whole life, so a
    # SUCCESSFUL read proves the creator is gone (stale leftover).
    for ($try = 0; $try -lt 2; $try++) {
        try {
            $stream = [System.IO.File]::Open(
                $LockPath,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None)
            $bytes = $Utf8NoBom.GetBytes([string]$PID)
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush()
            return $stream
        } catch {
            # Lockfile already present. Live holder or stale leftover?
        }

        try {
            $null = [System.IO.File]::ReadAllText($LockPath)
        } catch {
            # Cannot read it -> the holder still has it open exclusively.
            return $null
        }

        Write-Log 'WARN removing stale lockfile (readable, so no process holds it)'
        try {
            Remove-Item -LiteralPath $LockPath -Force -ErrorAction Stop
        } catch {
            return $null
        }
    }
    return $null
}

Write-Log 'START nightly vault audit'

$auditLock = $null
try {
    if (-not (Test-Path $PromptPath)) {
        throw "Prompt file not found: $PromptPath"
    }

    # audit-prompt.md is BOM-less UTF-8; without -Encoding UTF8 PS 5.1 decodes
    # it as ANSI and hands claude a mojibake prompt.
    $promptContent = Get-Content -Path $PromptPath -Raw -Encoding UTF8
    # Inject the configured vault root.
    $promptContent = $promptContent.Replace('{{VAULT_ROOT}}', $VaultRoot)

    if ($DryRun) {
        Write-Log "DRYRUN would invoke: claude -p <contents of $PromptPath> (VAULT_AUTOMATION=1)"
        Write-Log "DRYRUN prompt length: $($promptContent.Length) chars"
        Write-Log 'END nightly vault audit (dry run, outcome=skipped)'
        exit 0
    }

    # --- once-per-day guard ------------------------------------------------
    # A box that is not on 24/7 can miss a fixed nightly trigger, so the audit
    # is typically wired to several triggers (daily + at-logon + catch-up). All
    # can fire on the same calendar day; the audit only needs to run once. The
    # stamp is written ONLY on success, so a failed run is retried by the next
    # trigger.
    $today     = (Get-Date).ToString('yyyy-MM-dd')
    $lastAudit = ''
    if (Test-Path -LiteralPath $StampPath) {
        try {
            $lastAudit = ([System.IO.File]::ReadAllText($StampPath)).Trim()
        } catch {
            $lastAudit = ''
        }
    }
    if (($lastAudit -eq $today) -and (-not $Force)) {
        Write-Log "already audited today ($today) - skipping"
        Write-Log 'END nightly vault audit (outcome=skipped)'
        exit 0
    }

    # Not while the user is at the machine. The stamp is NOT written, so the
    # next trigger picks the day back up.
    if ((-not $Force) -and (Get-Command Get-UserBusyReason -ErrorAction SilentlyContinue)) {
        $busy = Get-UserBusyReason
        if ($null -ne $busy) {
            Write-Log "deferred: $busy - not stamping today"
            Write-Log 'END nightly vault audit (outcome=deferred)'
            exit 0
        }
    }

    # --- date range --------------------------------------------------------
    # Audit a RANGE, not just "today": from the last successful audit (floored
    # at $MaxLookbackDays) through today. On a machine that sleeps through the
    # nightly trigger, this makes days actually worked still get audited.
    $floor     = (Get-Date).AddDays(-$MaxLookbackDays).ToString('yyyy-MM-dd')
    $sinceDate = $lastAudit
    if ([string]::IsNullOrWhiteSpace($sinceDate) -or ([string]::Compare($sinceDate, $floor) -lt 0)) {
        $sinceDate = $floor
    }

    $runContext = @"

---

## Run context (injected by nightly-audit.ps1 - authoritative, overrides any date assumption above)

- Today is $today.
- Last successful audit: $(if ([string]::IsNullOrWhiteSpace($lastAudit)) { 'none on record' } else { $lastAudit }).
- Audit the date range **$sinceDate through $today inclusive**. Never look further back than $sinceDate.
"@
    $promptContent = $promptContent + $runContext

    Write-Log "auditing range $sinceDate .. $today"

    $auditLock = Get-VaultLock
    if ($null -eq $auditLock) {
        Write-Log 'deferred: drain in progress'
        Write-Log 'END nightly vault audit (outcome=deferred)'
        exit 0
    }

    $env:VAULT_AUTOMATION = '1'

    # --permission-mode acceptEdits: headless has no TTY, so the interactive
    # permission prompt auto-denies and every Write/Edit silently fails while
    # the process still exits 0. Scoped to this child only.
    $claudeOutput = claude -p --permission-mode acceptEdits "$promptContent" 2>&1
    $exitCode = $LASTEXITCODE

    Remove-Item Env:\VAULT_AUTOMATION -ErrorAction SilentlyContinue

    if ($null -eq $exitCode) {
        $exitCode = 0
    }

    if ($exitCode -eq 0) {
        try {
            [System.IO.File]::WriteAllText($StampPath, $today, $Utf8NoBom)
        } catch {
            # Not fatal - worst case the audit runs again later today.
            Write-Log "WARN could not write stamp file: $($_.Exception.Message)"
        }

        # Log what the child actually said. Exit 0 alone cannot distinguish a
        # real audit pass from a run that silently did nothing.
        $lastLine = '<no output>'
        if ($null -ne $claudeOutput) {
            $outLines = @($claudeOutput |
                          ForEach-Object { [string]$_ } |
                          Where-Object { $_.Trim() -ne '' })
            if ($outLines.Count -gt 0) { $lastLine = $outLines[-1] }
        }
        Write-Log "claude output (last line): $lastLine"
        Write-Log 'END nightly vault audit (outcome=success)'
    }
    else {
        Write-Log "claude -p exited with code $exitCode"
        Write-Log "claude output: $claudeOutput"
        Write-Log 'END nightly vault audit (outcome=failure)'
    }

    exit 0
}
catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    Write-Log 'END nightly vault audit (outcome=failure)'
    exit 0
}
finally {
    if ($null -ne $auditLock) {
        try { $auditLock.Close() } catch { }
        try { $auditLock.Dispose() } catch { }
        try {
            if (Test-Path -LiteralPath $LockPath) {
                Remove-Item -LiteralPath $LockPath -Force -ErrorAction Stop
            }
        } catch { }
    }
}
