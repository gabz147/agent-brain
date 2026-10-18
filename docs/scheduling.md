# Scheduling hygiene

`hygiene --fix` repairs only unambiguous metadata, index membership and priority aging; it makes no model calls and records its report in the controller's `state-v2/hygiene-latest.json`. Nothing schedules it for you. If you want it nightly, add one entry with your OS's own scheduler. Replace the paths with your controller folder (`automation_dir` in `~/.agent-brain/config.json`) and Python.

**Linux (cron)**, `crontab -e`, every night at 03:30:

```text
30 3 * * * python3 "$HOME/.agent-brain/automation/vaultctl.py" hygiene --fix >> "$HOME/.agent-brain/hygiene.log" 2>&1
```

**macOS (launchd)**: save as `~/Library/LaunchAgents/com.agent-brain.hygiene.plist`, then `launchctl load ~/Library/LaunchAgents/com.agent-brain.hygiene.plist`. launchd does not expand `~`, so write your home path out.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.agent-brain.hygiene</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>/Users/you/.agent-brain/automation/vaultctl.py</string>
    <string>hygiene</string><string>--fix</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/Users/you/.agent-brain/hygiene.log</string>
  <key>StandardErrorPath</key><string>/Users/you/.agent-brain/hygiene.log</string>
</dict></plist>
```

**Windows (Task Scheduler)**, one line in PowerShell:

```powershell
schtasks /Create /TN "Agent Brain hygiene" /SC DAILY /ST 03:30 /TR "\"$((Get-Command python).Source)\" \"$env:USERPROFILE\.agent-brain\automation\vaultctl.py\" hygiene --fix"
```

That task runs in a console window and does not wait for you to be idle. For a hidden run that defers while you are at the keyboard, in a fullscreen app or paused, use [contrib/windows-audit](../contrib/windows-audit/README.md) instead.

Check the result with `brain hygiene` (no `--fix`) or by reading `state-v2/hygiene-latest.json`; an exit code alone does not prove the run succeeded. To stop, remove the cron line, `launchctl unload` the plist, or `schtasks /Delete /TN "Agent Brain hygiene"`.
