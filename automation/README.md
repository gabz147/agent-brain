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
| `user-busy.ps1` | Shared presence guard plus helpers, dot-sourced by both runners. Defers work while you are at the machine (input idle < 5 min, or a fullscreen app is foreground) or while you have paused automation from Obsidian (`automation-state.json`). Also holds the deferral-streak logger and the cost-ledger append. |
| `run-hidden.vbs` | Launches a `.ps1` with no console window, so a scheduled run never flashes a window or steals focus from a fullscreen app. |

Loop guard: every headless child runs with `VAULT_AUTOMATION=1`, which the hooks check to avoid re-queuing their own runs.

**Working directory.** Task Scheduler starts scripts in `C:\WINDOWS\system32`, and a headless `claude -p` sandboxes to its working directory — so both runners set the child's cwd to the vault and pass `--add-dir` for the transcript tree (drainer) or the `.claude` dir (audit). Without that, every scheduled child is denied every path under your profile, says so, exits 0, and looks like a success. Which leads to:

**Success is verified, never assumed.** The drainer accepts a child run only if a vault note the child *named* in its last line changed after the child started, or the last line is an accepted no-op (`already captured in-session` for a live-captured session, `nothing recorded` on a transcript with fewer than 3 tool calls and under 1500 characters of assistant text). A `session limit` / `rate limit` line halts the batch without charging an attempt. The audit stamps its day only when the child ends with `audit complete: N notes scanned` (or a vault file changed) and never when the output says it was blocked.

**Pause toggle.** `automation-state.json` (`{"paused":true,"scope":"afk"|"all","since":ISO}`) is written by the Agent Pulse plugin's orb click or command palette. Scope `afk` pauses the drainer and audit; `all` also silences the Stop-hook checkpoint. A missing or unreadable file means not paused. The queue keeps accumulating while paused, and since Claude Code deletes transcripts after 30 days the drainer logs a warning (and the orb tooltip shows one) once the oldest queued session is 20 days old.

**Logs stay readable.** A deferral streak logs its first line, then one summary when a run finally proceeds (`deferred 14x since … (fullscreen x11, user active x3)`), with a daily "still deferred" line in between. Every child run appends a row (date, session, transcript KB, seconds, outcome, files written) to the `Automation Costs.md` ledger in the vault (`BRAIN_COST_LEDGER` overrides the path), so you can measure what the automation costs before changing its cadence.

Runtime state files these create — `queue.jsonl`, `queue.batch.jsonl`, `processed.jsonl`, `failed.jsonl`, `stop-state.json`, `automation-state.json`, `deferral-*.json`, `last-audit-date.txt`, `*.log`, `.drain.lock` — are gitignored. Do not commit them.

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
