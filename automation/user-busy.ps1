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
# If this fails to compile we degrade to the process list rather than silently
# assuming the user is away.
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
        if (!GetWindowRect(h, out r)) { return false; }
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
        return $false
    }
}

function Get-UserBusyReason {
    # Returns a human-readable reason to defer, or $null if it is safe to run.

    if (-not $script:NativeProbesOk) {
        # Degraded: cannot measure presence. Still honour the game list, and say so.
        foreach ($name in $script:BusyProcessNames) {
            if (Get-Process -Name $name -ErrorAction SilentlyContinue) {
                return "$name is running (idle detection unavailable)"
            }
        }
        return $null
    }

    $idle = Get-IdleSeconds
    if ($idle -lt 0) {
        return 'cannot determine idle time - deferring to be safe'
    }
    if ($idle -lt $script:IdleThresholdSec) {
        return ('user active (' + [int]$idle + 's idle, need ' + $script:IdleThresholdSec + 's)')
    }

    if (Test-ForegroundFullscreen) {
        return 'a fullscreen app is in the foreground'
    }

    foreach ($name in $script:BusyProcessNames) {
        if (Get-Process -Name $name -ErrorAction SilentlyContinue) {
            return "$name is running"
        }
    }

    return $null
}
