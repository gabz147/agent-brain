# user-busy.ps1 - shared "don't interrupt the user" guard.
#
# Dot-sourced by drain-queue.ps1 and nightly-audit.ps1.
#
# Why: these jobs spawn a headless `claude` session - a heavy CPU/IO burst. Even
# with no console window (see run-hidden.vbs) that is not acceptable while the
# user is doing anything. So the rule is not "which app is open" (a browser is
# ALWAYS open; that would mean never running). The rule is: only run when the
# user is genuinely away from the machine.
#
# Three checks, cheapest first:
#   1. Input idle time  - any keyboard/mouse input in the last $IdleThresholdSec
#                         means the user is at the machine. Covers browsing,
#                         gaming, working, everything.
#   2. Fullscreen app   - covers being idle but present: watching video, AFK in
#                         champ select, spectating. Borderless-fullscreen counts,
#                         since the window rect still covers the monitor.
#   3. Process list     - explicit belt-and-braces for games that might slip the
#                         first two (minimised launcher mid-queue, etc).
#
# NOTE: check 1 only sees input for the session the script runs in. These tasks
# run with LogonType=Interactive precisely so this works. Do not move them to
# S4U / session 0 - idle detection would silently always report "away".

# How long with no input before the machine counts as idle. Raise it if jobs
# still fire while you are mid-thought; lower it if they never get a window.
$script:IdleThresholdSec = 300      # 5 minutes

# Optional extra names. The idle + fullscreen checks above are the real rule and
# cover everything by default; this list is only for the narrow case of an app
# that must not be disturbed even while input is idle (e.g. a game left sitting
# in a lobby). Empty on purpose - add a process name (no .exe) if you hit that.
$script:BusyProcessNames = @()

# --- native input/window probes -------------------------------------------
# If this fails to compile, scheduled work defers rather than assuming the user is away.
$script:NativeProbesOk = $false
try {
    if (-not ('VaultUserActivity' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class VaultUserActivity
{
    [StructLayout(LayoutKind.Sequential)]
    public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }

    [DllImport("user32.dll")]
    private static extern bool GetLastInputInfo(ref LASTINPUTINFO plii);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern IntPtr GetShellWindow();

    [DllImport("user32.dll")]
    private static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

    // uint arithmetic wraps correctly, so ~49.7 day uptime rollover is safe.
    public static double IdleSeconds()
    {
        LASTINPUTINFO lii = new LASTINPUTINFO();
        lii.cbSize = (uint)Marshal.SizeOf(typeof(LASTINPUTINFO));
        if (!GetLastInputInfo(ref lii)) { return -1.0; }
        uint now = (uint)Environment.TickCount;
        return (double)(now - lii.dwTime) / 1000.0;
    }

    public static bool TryGetForegroundRect(out int left, out int top, out int right, out int bottom)
    {
        left = 0; top = 0; right = 0; bottom = 0;
        IntPtr h = GetForegroundWindow();
        if (h == IntPtr.Zero) { return false; }
        if (h == GetShellWindow()) { return false; }
        RECT r;
        if (!GetWindowRect(h, out r)) { throw new InvalidOperationException("Cannot inspect foreground window bounds"); }
        left = r.Left; top = r.Top; right = r.Right; bottom = r.Bottom;
        return true;
    }
}
'@ -ErrorAction Stop
    }
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
    $script:NativeProbesOk = $true
} catch {
    $script:NativeProbesOk = $false
}

function Get-IdleSeconds {
    if (-not $script:NativeProbesOk) { return -1 }
    try { return [VaultUserActivity]::IdleSeconds() } catch { return -1 }
}

function Test-ForegroundFullscreen {
    if (-not $script:NativeProbesOk) { return $false }
    try {
        $l = 0; $t = 0; $r = 0; $b = 0
        if (-not [VaultUserActivity]::TryGetForegroundRect([ref]$l, [ref]$t, [ref]$r, [ref]$b)) {
            return $false
        }
        $screen = [System.Windows.Forms.Screen]::AllScreens |
                  Where-Object { $_.Bounds.IntersectsWith((New-Object System.Drawing.Rectangle($l, $t, ($r - $l), ($b - $t)))) } |
                  Select-Object -First 1
        if ($null -eq $screen) { $screen = [System.Windows.Forms.Screen]::PrimaryScreen }
        $bounds = $screen.Bounds
        # Covers the monitor (allow a few px of border slop).
        return (($l -le $bounds.Left + 2) -and ($t -le $bounds.Top + 2) -and
                ($r -ge $bounds.Right - 2) -and ($b -ge $bounds.Bottom - 2))
    } catch {
        return $null
    }
}

function Get-UserBusyReason {
    # Returns a human-readable reason to defer, or $null if it is safe to run.

    if (-not $script:NativeProbesOk) {
        # Cannot establish an idle, non-fullscreen state; defer.
        foreach ($name in $script:BusyProcessNames) {
            if (Get-Process -Name $name -ErrorAction SilentlyContinue) {
                return "$name is running (idle detection unavailable)"
            }
        }
        return 'presence probes unavailable - deferring to be safe'
    }

    $idle = Get-IdleSeconds
    if ($idle -lt 0) {
        return 'cannot determine idle time - deferring to be safe'
    }
    if ($idle -lt $script:IdleThresholdSec) {
        return ('user active (' + [int]$idle + 's idle, need ' + $script:IdleThresholdSec + 's)')
    }

    $fullscreen = Test-ForegroundFullscreen
    if ($null -eq $fullscreen) { return 'cannot determine fullscreen state - deferring to be safe' }
    if ($fullscreen) {
        return 'a fullscreen app is in the foreground'
    }

    foreach ($name in $script:BusyProcessNames) {
        if (Get-Process -Name $name -ErrorAction SilentlyContinue) {
            return "$name is running"
        }
    }

    return $null
}

# =========================================================================
# Shared helpers (added 2026-09-03). Dot-sourced by drain-queue.ps1 and
# nightly-audit.ps1 alongside the presence guard above:
#   Get-AutomationPause     - the user's on/off toggle (automation-state.json,
#                             written by the Obsidian Agent Pulse plugin)
#   Update-DeferralStreak / Close-DeferralStreak
#                           - one log line per deferral streak, not per hour
# Cost/outcome records are now written by the shared Python controller.
# Interactive hooks fail open; uncertain scheduled presence/pause state defers.
# =========================================================================
$script:HelperDir = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($script:HelperDir)) { $script:HelperDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$script:AutomationStatePath = Join-Path $script:HelperDir 'automation-state.json'
$script:HelperUtf8 = New-Object System.Text.UTF8Encoding($false)

function Get-AutomationPause {
    # Returns a reason string when the user has paused automation for $Scope,
    # else $null. Scope 'afk' (drainer + audit) is paused by either
    # {"scope":"afk"} or {"scope":"all"}; scope 'all' (also the live Stop-hook
    # gate) only by {"scope":"all"}. A missing or unreadable file means NOT
    # paused. An unreadable existing toggle defers scheduled work.
    param([string]$Scope = 'afk')
    try {
        if (-not (Test-Path -LiteralPath $script:AutomationStatePath)) { return $null }
        $st = [System.IO.File]::ReadAllText($script:AutomationStatePath) | ConvertFrom-Json -ErrorAction Stop
        if (-not $st.paused) { return $null }
        $sc = [string]$st.scope
        if ([string]::IsNullOrWhiteSpace($sc)) { $sc = 'afk' }
        if (($Scope -eq 'all') -and ($sc -ne 'all')) { return $null }
        $since = ''
        try { $since = ([datetime]::Parse([string]$st.since)).ToLocalTime().ToString('yyyy-MM-dd HH:mm') } catch { $since = [string]$st.since }
        return ('paused by user (scope ' + $sc + ') since ' + $since)
    } catch {
        return 'pause state unreadable - deferring to be safe'
    }
}

function Get-DeferralReasonKey {
    param([string]$Reason)
    if ($Reason -match 'user active') { return 'user active' }
    if ($Reason -match 'fullscreen') { return 'fullscreen' }
    if ($Reason -match 'paused') { return 'paused' }
    if ($Reason -match 'already audited') { return 'already audited' }
    if ($Reason -match 'drain in progress') { return 'drain in progress' }
    return 'other'
}

function Update-DeferralStreak {
    # Call on every deferral or skip. Returns a line to log on the FIRST
    # deferral of a streak and roughly once a day after that (every 24th);
    # $null means stay silent. State: deferral-<Name>.json next to this file.
    param([string]$Name, [string]$Reason)
    $p = Join-Path $script:HelperDir ('deferral-' + $Name + '.json')
    $key = Get-DeferralReasonKey $Reason
    try {
        $st = $null
        if (Test-Path -LiteralPath $p) { $st = [System.IO.File]::ReadAllText($p) | ConvertFrom-Json -ErrorAction Stop }
        if ($null -eq $st) {
            $obj = @{ count = 1; since = (Get-Date).ToString('yyyy-MM-dd HH:mm'); reasons = @{ $key = 1 } }
            [System.IO.File]::WriteAllText($p, ($obj | ConvertTo-Json -Compress), $script:HelperUtf8)
            return ('deferred: ' + $Reason + ' (streak started; later deferrals are summarised when a run proceeds)')
        }
        $count = [int]$st.count + 1
        $reasons = @{}
        foreach ($prop in $st.reasons.PSObject.Properties) { $reasons[$prop.Name] = [int]$prop.Value }
        if ($reasons.ContainsKey($key)) { $reasons[$key]++ } else { $reasons[$key] = 1 }
        $obj = @{ count = $count; since = [string]$st.since; reasons = $reasons }
        [System.IO.File]::WriteAllText($p, ($obj | ConvertTo-Json -Compress), $script:HelperUtf8)
        if (($count % 24) -eq 0) {
            $parts = @(); foreach ($k in $reasons.Keys) { $parts += ($k + ' x' + $reasons[$k]) }
            return ('still deferred: ' + $Reason + ' - ' + $count + 'x since ' + $st.since + ' (' + ($parts -join ', ') + ')')
        }
        return $null
    } catch {
        return ('deferred: ' + $Reason)
    }
}

function Close-DeferralStreak {
    # Call when a run actually proceeds. Returns a one-line summary of the
    # streak that just ended (if it had more than one deferral), else $null.
    param([string]$Name)
    $p = Join-Path $script:HelperDir ('deferral-' + $Name + '.json')
    try {
        if (-not (Test-Path -LiteralPath $p)) { return $null }
        $st = [System.IO.File]::ReadAllText($p) | ConvertFrom-Json -ErrorAction Stop
        Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
        if ([int]$st.count -le 1) { return $null }
        $parts = @()
        foreach ($prop in $st.reasons.PSObject.Properties) { $parts += ($prop.Name + ' x' + $prop.Value) }
        return ('deferred ' + $st.count + 'x since ' + $st.since + ' (' + ($parts -join ', ') + ') - proceeding now')
    } catch {
        return $null
    }
}
