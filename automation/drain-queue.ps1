<#
.SYNOPSIS
    Drains the vault-automation session queue into the Obsidian vault.

.DESCRIPTION
    A SessionEnd hook appends one JSON line per finished Claude Code session to
    queue.jsonl:  {"ts","session_id","transcript_path","cwd"}

    This script consumes that queue. Under the drain lock it RENAMES
    queue.jsonl to queue.batch.jsonl and reads work only from that batch file.
    The SessionEnd hook takes no lock, so it keeps appending to a fresh
    queue.jsonl that the drainer never overwrites - retry entries are APPENDED
    back onto queue.jsonl, never written over it. Every entry disposition is
    checkpointed by rewriting the batch file with the entries not yet handled,
    so a crash cannot make an already-processed session run twice.

    For each entry it runs a headless `claude -p` pass using capture-prompt.md,
    which reads the transcript and writes the corresponding vault notes. The
    child is launched with a hard timeout so a hung child cannot hold the drain
    lock forever.

    Windows PowerShell 5.1 compatible (no &&, ||, ternary, ?? or -AsHashtable).

    PORTABILITY: this script locates its own directory via $PSScriptRoot, so it
    runs from wherever you place the automation folder. The vault root is read
    from BRAIN_VAULT_ROOT (fallback ~/Documents/Brain) and injected into the
    capture prompt in place of {{VAULT_ROOT}}.

.PARAMETER DryRun
    Do everything except invoking `claude -p` and except consuming the queue.
    Logs what it WOULD do. queue.jsonl is left untouched (not even renamed).
#>

[CmdletBinding()]
param(
    [switch]$DryRun,
    # Bypass the user-presence guard. For manual runs.
    [switch]$Force
)

Set-StrictMode -Off
$ErrorActionPreference = 'Continue'

# ---------------------------------------------------------------- paths ----
$Root          = if ($env:BRAIN_AUTOMATION_DIR) { $env:BRAIN_AUTOMATION_DIR } else { $PSScriptRoot }
$QueuePath     = Join-Path $Root 'queue.jsonl'
$BatchPath     = Join-Path $Root 'queue.batch.jsonl'
$BatchTmpPath  = Join-Path $Root 'queue.batch.jsonl.tmp'
$ProcessedPath = Join-Path $Root 'processed.jsonl'
$FailedPath    = Join-Path $Root 'failed.jsonl'
$LogPath       = Join-Path $Root 'drain.log'
$LockPath      = Join-Path $Root '.drain.lock'
$PromptPath    = Join-Path $Root 'capture-prompt.md'

# Vault root injected into the capture prompt.
$VaultRoot     = if ($env:BRAIN_VAULT_ROOT) { $env:BRAIN_VAULT_ROOT } else { Join-Path $env:USERPROFILE 'Documents\Brain' }

$MaxAttempts   = 3
$ChildTimeoutMs = 900000    # 15 minutes per headless child
$Utf8NoBom     = New-Object System.Text.UTF8Encoding($false)

# Shared guard: never run while the user is at the machine (see user-busy.ps1).
$BusyGuardPath = Join-Path $Root 'user-busy.ps1'
if (Test-Path -LiteralPath $BusyGuardPath) {
    . $BusyGuardPath
}

# Session ids re-queued during THIS run. A recovered batch appends its retries
# straight back onto queue.jsonl; if that same queue is then rotated in the
# same run we must not process the entry twice (and burn two attempts).
$script:RequeuedIds = @{}

# ------------------------------------------------------------- helpers ----
function Write-DrainLog {
    param([string]$Message, [string]$Level = 'INFO')

    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    $line  = '[' + $stamp + '] [' + $Level + '] ' + $Message
    try {
        [System.IO.File]::AppendAllText($LogPath, $line + "`r`n", $Utf8NoBom)
    } catch {
        # Logging must never take the run down.
    }
    Write-Host $line
}

function Add-JsonLine {
    param([string]$Path, $Object)

    try {
        $json = $Object | ConvertTo-Json -Depth 10 -Compress
        [System.IO.File]::AppendAllText($Path, $json + "`r`n", $Utf8NoBom)
        return $true
    } catch {
        Write-DrainLog ('failed to append to ' + $Path + ': ' + $_.Exception.Message) 'ERROR'
        return $false
    }
}

function Write-BatchFile {
    param([object[]]$Entries)

    # Temp file first, then atomic-ish move, so a crash mid-rewrite cannot
    # destroy the batch. Only the drainer ever touches this file.
    $lines = New-Object System.Collections.Generic.List[string]
    foreach ($e in $Entries) {
        $lines.Add(($e | ConvertTo-Json -Depth 10 -Compress))
    }
    [System.IO.File]::WriteAllLines($BatchTmpPath, $lines.ToArray(), $Utf8NoBom)
    Move-Item -LiteralPath $BatchTmpPath -Destination $BatchPath -Force
}

function Remove-BatchFile {
    try {
        if (Test-Path -LiteralPath $BatchPath) {
            Remove-Item -LiteralPath $BatchPath -Force -ErrorAction Stop
        }
        return $true
    } catch {
        Write-DrainLog ('failed to remove batch file: ' + $_.Exception.Message) 'ERROR'
        return $false
    }
}

function Test-HasContent {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        $lines = @(Get-Content -LiteralPath $Path -ErrorAction Stop |
                   Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        return ($lines.Count -gt 0)
    } catch {
        return $false
    }
}

function Get-EntryAttempts {
    param($Entry)

    $val = $null
    if ($null -ne $Entry.PSObject.Properties['attempts']) {
        $val = $Entry.attempts
    }
    if ($null -eq $val) { return 0 }
    $n = 0
    if ([int]::TryParse([string]$val, [ref]$n)) { return $n }
    return 0
}

function Set-EntryAttempts {
    param($Entry, [int]$Count)

    if ($null -eq $Entry.PSObject.Properties['attempts']) {
        Add-Member -InputObject $Entry -MemberType NoteProperty -Name 'attempts' -Value $Count
    } else {
        $Entry.attempts = $Count
    }
}

function Get-EntryProp {
    param($Entry, [string]$Name)

    if ($null -eq $Entry) { return $null }
    if ($null -eq $Entry.PSObject.Properties[$Name]) { return $null }
    return $Entry.$Name
}

# ---------------------------------------------------------------- lock ----
function Get-DrainLock {
    # Returns an open FileStream on success, $null if another live drain holds it.
    #
    # The holder keeps this file open with FileShare::None for its entire life,
    # so a SUCCESSFUL read of the lockfile already proves the creator is gone.
    # A read failure is the real liveness test - no PID inspection (PID reuse
    # would wedge draining forever).
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
            # Lockfile already present. Decide: live holder or stale leftover?
        }

        try {
            $null = [System.IO.File]::ReadAllText($LockPath)
        } catch {
            # Cannot even read it -> the holder still has it open exclusively.
            return $null
        }

        Write-DrainLog 'removing stale lockfile (readable, so no process holds it)' 'WARN'
        try {
            Remove-Item -LiteralPath $LockPath -Force -ErrorAction Stop
        } catch {
            return $null
        }
    }
    return $null
}

# ----------------------------------------------------------- the child ----
function Invoke-CaptureChild {
    param([string]$Prompt, [string]$SessionId)

    # Returns the child exit code. A timeout is reported as exit 1 so the
    # existing attempt / poison path handles it like any other failure.
    $tmpPrompt = $null
    $tmpOut    = $null
    $childExit = 1
    try {
        $tmpPrompt = [System.IO.Path]::GetTempFileName()
        $tmpOut    = [System.IO.Path]::GetTempFileName()
        [System.IO.File]::WriteAllText($tmpPrompt, $Prompt, $Utf8NoBom)

        # VAULT_AUTOMATION=1 is set on this process; Start-Process with
        # -NoNewWindow (UseShellExecute=false) hands the child a copy of this
        # process environment block, so the loop guard inherits.
        # --permission-mode acceptEdits: headless has no TTY, so the interactive
        # permission prompt auto-denies and every Write/Edit silently fails while
        # the process still exits 0. Scoped to this child only - interactive
        # sessions keep their normal prompting.
        $p = Start-Process -FilePath 'claude' `
                           -ArgumentList '-p', '--permission-mode', 'acceptEdits' `
                           -RedirectStandardInput $tmpPrompt `
                           -RedirectStandardOutput $tmpOut `
                           -NoNewWindow -PassThru -ErrorAction Stop

        # PS 5.1 quirk: Start-Process -PassThru returns a Process whose
        # ExitCode stays $null after WaitForExit unless the handle has been
        # cached. Touching .Handle forces .NET to hold it, so ExitCode is
        # populated once the child exits. Without this every child - including
        # successful ones - reads as a failure.
        $null = $p.Handle

        if ($p.WaitForExit($ChildTimeoutMs)) {
            $childExit = $p.ExitCode
            # Last-resort fallback only; with the handle cached above the
            # normal path is a real exit code (including 0).
            if ($null -eq $childExit) { $childExit = 1 }
        } else {
            Write-DrainLog ('TIMEOUT ' + $SessionId + ' - claude child pid ' + $p.Id +
                            ' exceeded ' + [int]($ChildTimeoutMs / 1000) + 's - killing tree') 'ERROR'
            try {
                & taskkill /PID $p.Id /T /F 2>&1 | Out-Null
            } catch {
                Write-DrainLog ('taskkill failed for pid ' + $p.Id + ': ' + $_.Exception.Message) 'ERROR'
            }
            $childExit = 1
        }

        # capture-prompt.md tells the child to finish with a single line naming
        # the files it wrote, or 'nothing recorded' if it bailed. Log it: an
        # exit 0 alone cannot distinguish a real capture from a silent no-op.
        try {
            $outLines = @(Get-Content -LiteralPath $tmpOut -Encoding UTF8 -ErrorAction Stop |
                          ForEach-Object { [string]$_ } |
                          Where-Object { $_.Trim() -ne '' })
            if ($outLines.Count -gt 0) {
                Write-DrainLog ('CHILD ' + $SessionId + ': ' + $outLines[-1])
            } else {
                Write-DrainLog ('CHILD ' + $SessionId + ': <no output>')
            }
        } catch {
            Write-DrainLog ('CHILD ' + $SessionId + ': <output unreadable>')
        }
    } catch {
        Write-DrainLog ('claude invocation threw for ' + $SessionId + ': ' + $_.Exception.Message) 'ERROR'
        $childExit = 1
    } finally {
        if ($null -ne $tmpPrompt) {
            try { Remove-Item -LiteralPath $tmpPrompt -Force -ErrorAction SilentlyContinue } catch { }
        }
        if ($null -ne $tmpOut) {
            try { Remove-Item -LiteralPath $tmpOut -Force -ErrorAction SilentlyContinue } catch { }
        }
    }
    return $childExit
}

# --------------------------------------------------------- batch drain ----
function Invoke-DrainBatch {
    param(
        [string]$SourcePath,
        [string]$Label,
        [string]$PromptTemplate,
        [bool]$IsDryRun
    )

    $result = @{ ok = 0; retry = 0; poison = 0; deferred = 0; halted = $false }

    $rawLines = @()
    try {
        $rawLines = @(Get-Content -LiteralPath $SourcePath -ErrorAction Stop |
                      Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    } catch {
        $rawLines = @()
    }
    if ($rawLines.Count -eq 0) {
        if (-not $IsDryRun) { [void](Remove-BatchFile) }
        return $result
    }

    # -- parse + dedupe by session_id (newest wins) --------------------------
    $ordered = New-Object System.Collections.Specialized.OrderedDictionary
    $badLines = 0
    $idx = 0
    foreach ($line in $rawLines) {
        $idx++
        $obj = $null
        try {
            $obj = $line | ConvertFrom-Json -ErrorAction Stop
        } catch {
            $badLines++
            if ($IsDryRun) {
                Write-DrainLog ('unparseable queue line ' + $idx + ' - DRY RUN, not journalled') 'WARN'
                continue
            }
            Write-DrainLog ('unparseable queue line ' + $idx + ' - moving to failed.jsonl') 'ERROR'
            $bad = New-Object psobject
            Add-Member -InputObject $bad -MemberType NoteProperty -Name 'ts' -Value (Get-Date).ToString('o')
            Add-Member -InputObject $bad -MemberType NoteProperty -Name 'reason' -Value 'unparseable-json'
            # [string] strips the ETS members (PSPath/PSDrive/PSProvider) that
            # Get-Content attaches. Without the cast ConvertTo-Json -Depth 10
            # walks the whole provider object graph and effectively hangs.
            Add-Member -InputObject $bad -MemberType NoteProperty -Name 'raw' -Value ([string]$line)
            [void](Add-JsonLine -Path $FailedPath -Object $bad)
            continue
        }

        $sid = Get-EntryProp $obj 'session_id'
        if ([string]::IsNullOrWhiteSpace([string]$sid)) {
            $sid = 'noid-' + $idx
        }
        $key = [string]$sid

        if ($ordered.Contains($key)) {
            # Later line in an append-only queue is the newer one; fall back to
            # ts comparison when both timestamps parse.
            $keepNew = $true
            $oldTs = Get-EntryProp $ordered[$key] 'ts'
            $newTs = Get-EntryProp $obj 'ts'
            if ($null -ne $oldTs -and $null -ne $newTs) {
                try {
                    $o = [datetime]::Parse([string]$oldTs)
                    $n = [datetime]::Parse([string]$newTs)
                    if ($n -lt $o) { $keepNew = $false }
                } catch {
                    $keepNew = $true
                }
            }
            if ($keepNew) {
                # Carry forward the attempt count from the entry being replaced.
                $prevAttempts = Get-EntryAttempts $ordered[$key]
                if ((Get-EntryAttempts $obj) -lt $prevAttempts) {
                    Set-EntryAttempts $obj $prevAttempts
                }
                $ordered[$key] = $obj
            }
            Write-DrainLog ('duplicate session_id ' + $key + ' - keeping newest') 'INFO'
        } else {
            $ordered.Add($key, $obj)
        }
    }

    $pending = New-Object System.Collections.Generic.List[object]
    foreach ($k in @($ordered.Keys)) { $pending.Add($ordered[$k]) }

    Write-DrainLog ('[' + $Label + '] lines: ' + $rawLines.Count + ' | unparseable: ' + $badLines +
                    ' | unique sessions: ' + $pending.Count)

    # Checkpoint 0: the batch now holds exactly the deduped, parseable work.
    if (-not $IsDryRun) {
        try {
            if ($pending.Count -gt 0) {
                Write-BatchFile -Entries $pending.ToArray()
            } else {
                [void](Remove-BatchFile)
            }
        } catch {
            Write-DrainLog ('batch checkpoint FAILED: ' + $_.Exception.Message) 'ERROR'
            $result['halted'] = $true
            return $result
        }
    }

    $prevFlag = $env:VAULT_AUTOMATION
    $env:VAULT_AUTOMATION = '1'
    try {
        while ($pending.Count -gt 0) {
            $e = $pending[0]
            $sid = [string](Get-EntryProp $e 'session_id')
            $tp  = [string](Get-EntryProp $e 'transcript_path')
            $cwd = [string](Get-EntryProp $e 'cwd')
            if ([string]::IsNullOrWhiteSpace($cwd)) { $cwd = '(unknown)' }

            $keepInBatch = $false

            if ((-not $IsDryRun) -and $script:RequeuedIds.ContainsKey($sid)) {
                # Already appended back onto queue.jsonl earlier this run - but
                # that queue may since have been rotated INTO this batch, so the
                # entry now exists nowhere else. Put it back on the live queue
                # instead of dropping it on the floor.
                if (Add-JsonLine -Path $QueuePath -Object $e) {
                    Write-DrainLog ('deferring ' + $sid + ' - already re-queued this run -> re-appended to queue.jsonl') 'INFO'
                    $result['deferred']++
                } else {
                    Write-DrainLog ('queue.jsonl append failed for deferred ' + $sid + ' - carrying entry forward') 'ERROR'
                    $keepInBatch = $true
                }
            }
            elseif ([string]::IsNullOrWhiteSpace($tp) -or -not (Test-Path -LiteralPath $tp)) {
                Write-DrainLog ('skip ' + $sid + ' - transcript missing: ' + $tp) 'WARN'
                if (-not $IsDryRun) {
                    Add-Member -InputObject $e -MemberType NoteProperty -Name 'reason' -Value 'transcript-missing' -Force
                    Add-Member -InputObject $e -MemberType NoteProperty -Name 'failed_at' -Value (Get-Date).ToString('o') -Force
                    if (-not (Add-JsonLine -Path $FailedPath -Object $e)) {
                        # Never let a failed journal append erase the only record.
                        Write-DrainLog ('failed.jsonl append failed for ' + $sid + ' - carrying entry forward') 'ERROR'
                        $keepInBatch = $true
                    }
                }
            }
            elseif ($IsDryRun) {
                $prompt = $PromptTemplate.Replace('{{TRANSCRIPT_PATH}}', $tp).Replace('{{SESSION_CWD}}', $cwd)
                Write-DrainLog ('DRY RUN would run: claude -p <capture-prompt.md> for session ' + $sid +
                                ' | transcript=' + $tp + ' | cwd=' + $cwd + ' | VAULT_AUTOMATION=1 | prompt chars=' + $prompt.Length)
            }
            else {
                $prompt = $PromptTemplate.Replace('{{TRANSCRIPT_PATH}}', $tp).Replace('{{SESSION_CWD}}', $cwd)
                Write-DrainLog ('processing session ' + $sid + ' | transcript=' + $tp)

                $childExit = Invoke-CaptureChild -Prompt $prompt -SessionId $sid

                if ($childExit -eq 0) {
                    $result['ok']++
                    Add-Member -InputObject $e -MemberType NoteProperty -Name 'processed_at' -Value (Get-Date).ToString('o') -Force
                    [void](Add-JsonLine -Path $ProcessedPath -Object $e)
                    Write-DrainLog ('OK ' + $sid + ' -> processed.jsonl')
                } else {
                    $attempts = (Get-EntryAttempts $e) + 1
                    Set-EntryAttempts $e $attempts
                    Write-DrainLog ('FAIL ' + $sid + ' (claude exit ' + $childExit + ') attempt ' + $attempts + '/' + $MaxAttempts) 'ERROR'
                    if ($attempts -ge $MaxAttempts) {
                        Add-Member -InputObject $e -MemberType NoteProperty -Name 'reason' -Value ('max-attempts (' + $MaxAttempts + ')') -Force
                        Add-Member -InputObject $e -MemberType NoteProperty -Name 'failed_at' -Value (Get-Date).ToString('o') -Force
                        if (Add-JsonLine -Path $FailedPath -Object $e) {
                            $result['poison']++
                            Write-DrainLog ('POISON ' + $sid + ' -> failed.jsonl (dropped from queue)') 'ERROR'
                        } else {
                            # Never let a failed journal append erase the only record.
                            Write-DrainLog ('failed.jsonl append failed for ' + $sid + ' - carrying entry forward') 'ERROR'
                            $keepInBatch = $true
                        }
                    } else {
                        # Append the retry back onto the LIVE queue before it
                        # leaves the batch, so a crash can only duplicate it
                        # (dedupe by session_id absorbs that), never lose it.
                        if (Add-JsonLine -Path $QueuePath -Object $e) {
                            $result['retry']++
                            $script:RequeuedIds[$sid] = $true
                            Write-DrainLog ('RETRY ' + $sid + ' -> appended back to queue.jsonl')
                        } else {
                            Write-DrainLog ('queue.jsonl append failed for ' + $sid + ' - halting batch, entries stay in queue.batch.jsonl') 'ERROR'
                            $result['halted'] = $true
                            break
                        }
                    }
                }
            }

            if ($keepInBatch) {
                Write-DrainLog ('halting batch - ' + $sid + ' stays in queue.batch.jsonl for the next run') 'ERROR'
                $result['halted'] = $true
                break
            }

            # -- per-entry checkpoint: batch now holds only unhandled work ----
            $pending.RemoveAt(0)
            if (-not $IsDryRun) {
                try {
                    if ($pending.Count -gt 0) {
                        Write-BatchFile -Entries $pending.ToArray()
                    } else {
                        [void](Remove-BatchFile)
                    }
                } catch {
                    Write-DrainLog ('batch checkpoint FAILED: ' + $_.Exception.Message) 'ERROR'
                    $result['halted'] = $true
                    break
                }
            }
        }
    } finally {
        if ($null -eq $prevFlag) {
            Remove-Item Env:\VAULT_AUTOMATION -ErrorAction SilentlyContinue
        } else {
            $env:VAULT_AUTOMATION = $prevFlag
        }
    }

    return $result
}

# ---------------------------------------------------------------- main ----
# Nothing to do at all: stay quiet.
$hasQueue = Test-HasContent $QueuePath
$hasBatch = Test-HasContent $BatchPath
if ((-not $hasQueue) -and (-not $hasBatch)) { exit 0 }

# There IS work, but not while the user is at the machine. Take no lock and
# consume nothing - the queue is left exactly as-is for the next scheduled run.
if ((-not $Force) -and (Get-Command Get-UserBusyReason -ErrorAction SilentlyContinue)) {
    $busy = Get-UserBusyReason
    if ($null -ne $busy) {
        Write-DrainLog ('deferred: ' + $busy + ' - queue left intact') 'INFO'
        exit 0
    }
}

$lock = Get-DrainLock
if ($null -eq $lock) {
    Write-DrainLog 'drain already running (lockfile held) - exiting' 'INFO'
    exit 0
}

$exitCode = 0
try {
    $mode = 'live'
    if ($DryRun) { $mode = 'DRY RUN' }
    Write-DrainLog ('=== drain start (' + $mode + ', pid ' + $PID + ') ===')

    if (-not (Test-Path -LiteralPath $PromptPath)) {
        Write-DrainLog ('capture-prompt.md missing at ' + $PromptPath + ' - aborting') 'ERROR'
        exit 1
    }
    $promptTemplate = [System.IO.File]::ReadAllText($PromptPath)
    # Inject the configured vault root and automation dir into the prompt.
    $promptTemplate = $promptTemplate.Replace('{{VAULT_ROOT}}', $VaultRoot).Replace('{{AUTOMATION_DIR}}', $Root)

    $totOk = 0; $totRetry = 0; $totPoison = 0; $totDeferred = 0

    if ($DryRun) {
        # Never rename, never write: report on whatever is queued.
        $src = $QueuePath
        $label = 'queue.jsonl'
        if (Test-Path -LiteralPath $BatchPath) {
            $src = $BatchPath
            $label = 'queue.batch.jsonl'
        }
        $r = Invoke-DrainBatch -SourcePath $src -Label $label -PromptTemplate $promptTemplate -IsDryRun $true
        $totOk += $r['ok']; $totRetry += $r['retry']; $totPoison += $r['poison']; $totDeferred += $r['deferred']
        Write-DrainLog ('DRY RUN ' + $label + ' left untouched')
    }
    else {
        # 1. Recover a batch left behind by an interrupted run.
        if (Test-Path -LiteralPath $BatchPath) {
            Write-DrainLog 'recovering queue.batch.jsonl left by an interrupted run' 'WARN'
            $r = Invoke-DrainBatch -SourcePath $BatchPath -Label 'recovered batch' -PromptTemplate $promptTemplate -IsDryRun $false
            $totOk += $r['ok']; $totRetry += $r['retry']; $totPoison += $r['poison']; $totDeferred += $r['deferred']
            if ($r['halted']) { $exitCode = 1 }
        }

        # 2. Rotate the live queue into a batch and drain that. The hook keeps
        #    appending to the fresh queue.jsonl, which we never overwrite.
        if (Test-Path -LiteralPath $BatchPath) {
            Write-DrainLog 'batch file still present - deferring queue rotation to the next run' 'WARN'
        }
        elseif (Test-HasContent $QueuePath) {
            $rotated = $false
            try {
                Move-Item -LiteralPath $QueuePath -Destination $BatchPath -ErrorAction Stop
                $rotated = $true
                Write-DrainLog 'rotated queue.jsonl -> queue.batch.jsonl'
            } catch {
                Write-DrainLog ('failed to rotate queue.jsonl -> queue.batch.jsonl: ' + $_.Exception.Message) 'ERROR'
                $exitCode = 1
            }
            if ($rotated) {
                $r = Invoke-DrainBatch -SourcePath $BatchPath -Label 'batch' -PromptTemplate $promptTemplate -IsDryRun $false
                $totOk += $r['ok']; $totRetry += $r['retry']; $totPoison += $r['poison']; $totDeferred += $r['deferred']
                if ($r['halted']) { $exitCode = 1 }
            }
        }
    }

    Write-DrainLog ('=== drain end (ok=' + $totOk + ' retry=' + $totRetry + ' poison=' + $totPoison +
                    ' deferred=' + $totDeferred + ') ===')
} catch {
    Write-DrainLog ('unhandled error: ' + $_.Exception.Message) 'ERROR'
    $exitCode = 1
} finally {
    if ($null -ne $lock) {
        try { $lock.Close() } catch { }
        try { $lock.Dispose() } catch { }
    }
    try {
        if (Test-Path -LiteralPath $LockPath) {
            Remove-Item -LiteralPath $LockPath -Force -ErrorAction Stop
        }
    } catch { }
}

exit $exitCode
