# Automation module (OPTIONAL, ADVANCED)

This turns the vault **self-populating**: finished Claude Code sessions get written up as daily notes automatically, and a nightly pass audits the vault for drift. **You do not need this for the brain to work** — the core hooks (frontmatter validation + the Stop-gate checkpoint prompt) already keep the vault healthy when you drive it interactively. Skip this whole folder if you just want the memory system.

It is Windows-only (PowerShell 5.1 + Task Scheduler + a VBS launcher) and depends on the `claude` CLI being on PATH and logged in.

## Pieces

| File | Role |
|---|---|
| `session-end-enqueue.js` (in `hooks/vault/`) | SessionEnd hook: appends each finished session to `queue.jsonl`. |
| `drain-queue.ps1` | Consumes `queue.jsonl`, runs headless `claude -p` per session against `capture-prompt.md` to write daily notes. Lock + batch + retry/poison handling. |
| `nightly-audit.ps1` | Once/day: runs headless `claude -p` against `audit-prompt.md` to fix frontmatter drift, age Active Priorities, sync folder indexes, backfill missing daily notes. |
| `capture-prompt.md` / `audit-prompt.md` | The headless prompts. `{{VAULT_ROOT}}` / `{{AUTOMATION_DIR}}` / `{{TRANSCRIPT_PATH}}` / `{{SESSION_CWD}}` are substituted by the scripts at runtime. |
| `user-busy.ps1` | Shared presence guard: dot-sourced by both runners. Defers work while you are at the machine (input idle < 5 min, or a fullscreen app is foreground). |
| `run-hidden.vbs` | Launches a `.ps1` with no console window, so a scheduled run never flashes a window or steals focus from a fullscreen app. |

Loop guard: every headless child runs with `VAULT_AUTOMATION=1`, which the hooks check to avoid re-queuing their own runs.

Runtime state files these create — `queue.jsonl`, `queue.batch.jsonl`, `processed.jsonl`, `failed.jsonl`, `stop-state.json`, `last-audit-date.txt`, `*.log`, `.drain.lock` — are gitignored. Do not commit them.

## Install

1. Copy this `automation/` folder to your automation dir, e.g. `C:\Users\<you>\.claude\vault-automation\`.
2. Make sure `BRAIN_VAULT_ROOT` (and optionally `BRAIN_AUTOMATION_DIR`) are set as user environment variables so the scripts and hooks agree on paths.
3. Confirm `claude` runs from a plain PowerShell prompt and is logged in.
4. Smoke-test without touching anything:
   ```powershell
   powershell -ExecutionPolicy Bypass -File "C:\Users\<you>\.claude\vault-automation\drain-queue.ps1" -DryRun
   powershell -ExecutionPolicy Bypass -File "C:\Users\<you>\.claude\vault-automation\nightly-audit.ps1" -DryRun
   ```
   Check `drain.log` / `audit.log`.
5. Register the scheduled tasks (adjust the paths). Run from an elevated PowerShell:

   ```powershell
   $auto = "C:\Users\<you>\.claude\vault-automation"

   # Drainer: every 15 min, hidden, only when you are away (the script self-defers).
   $drainAction  = New-ScheduledTaskAction -Execute "wscript.exe" `
     -Argument "`"$auto\run-hidden.vbs`" `"$auto\drain-queue.ps1`""
   $drainTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
     -RepetitionInterval (New-TimeSpan -Minutes 15)
   Register-ScheduledTask -TaskName "VaultDrainQueue" -Action $drainAction `
     -Trigger $drainTrigger -RunLevel Limited -Description "Drain Claude session queue into the vault"

   # Nightly audit: 03:30 daily + at logon, catch-up if missed.
   $auditAction   = New-ScheduledTaskAction -Execute "wscript.exe" `
     -Argument "`"$auto\run-hidden.vbs`" `"$auto\nightly-audit.ps1`""
   $auditTrigger1 = New-ScheduledTaskTrigger -Daily -At 3:30am
   $auditTrigger2 = New-ScheduledTaskTrigger -AtLogOn
   $settings      = New-ScheduledTaskSettingsSet -StartWhenAvailable
   Register-ScheduledTask -TaskName "VaultNightlyAudit" -Action $auditAction `
     -Trigger $auditTrigger1,$auditTrigger2 -Settings $settings -RunLevel Limited `
     -Description "Nightly Obsidian vault audit"
   ```

   Tasks must run as your interactive user (LogonType Interactive), NOT as SYSTEM / S4U — the presence guard reads input-idle time, which only works in your own session.

6. Tune `user-busy.ps1` (`$IdleThresholdSec`, `$BusyProcessNames`) if jobs fire while you are working, or never get a window.

## Uninstall

```powershell
Unregister-ScheduledTask -TaskName "VaultDrainQueue"  -Confirm:$false
Unregister-ScheduledTask -TaskName "VaultNightlyAudit" -Confirm:$false
```

Then remove the SessionEnd hook from `settings.json` if you no longer want sessions queued.
