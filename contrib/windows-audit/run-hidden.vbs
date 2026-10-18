' run-hidden.vbs - launch a PowerShell script with NO console window.
'
' Why this exists:
'   Task Scheduler running `powershell.exe -WindowStyle Hidden` still creates a
'   conhost.exe console window and only hides it afterwards. That flash is long
'   enough to steal foreground focus, which tabs a fullscreen game out.
'   wscript.exe + WshShell.Run with intWindowStyle=0 never creates the window
'   in the first place, so there is nothing to steal focus.
'
' Usage:
'   wscript.exe "run-hidden.vbs" "C:\path\to\script.ps1" [extra ps1 args...]
'
' Waits for the child (bWaitOnReturn = True) so the scheduled task's runtime
' and ExecutionTimeLimit reflect the real work, and propagates its exit code.

Option Explicit

Dim shell, ps1, cmd, i, rc

If WScript.Arguments.Count < 1 Then
    WScript.Quit 2
End If

Set shell = CreateObject("WScript.Shell")

ps1 = WScript.Arguments(0)
cmd = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & ps1 & """"

For i = 1 To WScript.Arguments.Count - 1
    cmd = cmd & " " & WScript.Arguments(i)
Next

rc = shell.Run(cmd, 0, True)

WScript.Quit rc
