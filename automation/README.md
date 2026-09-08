# Shared controller and optional Windows scheduling

The Python controller is required for live vault writes and checkpoints. The PowerShell runners and Task Scheduler jobs are optional. Installing these files alone does not start jobs or make model calls.

## Components

| Files | Purpose |
|---|---|
| `vaultctl.py`, `vault_core.py`, `vault-schema.json` | Shared CLI, schema, containment, locks, snapshots, atomic commits, and exact-byte restore |
| `vault_sources.py` | Claude/Codex transcript fragments, real model attribution, and source-bound coverage |
| `vault_capture.py`, `capture-prompt.md` | Restricted read-only model proposals; controller alone writes |
| `vault_queue.py` | Durable intake, failure recovery, incremental capture, and idle Codex discovery |
| `vault_hooks.py` | Live Stop decision logic; a request never claims capture |
| `vault_hygiene.py`, `vault_runtime.py` | Deterministic schema/index/priority checks, boot/skill parity, and approved runtime drift checks |
| `invoke-vault-job.ps1`, `drain-queue.ps1`, `nightly-audit.ps1` | Guarded scheduled entry points; only verified audit results advance the day stamp |
| `user-busy.ps1`, `run-hidden.vbs` | Interactive idle/fullscreen/pause guards and a windowless launcher |
| `tests/` | Temporary-vault regression tests; no paid model calls |

## Live commands

Run with the configured environment, or provide `--vault`, `--state`, and `--backups` **before** the subcommand for an isolated fixture.

```powershell
python vaultctl.py inspect '02 - Example Project/Example.md'
python vaultctl.py commit --model '<verified-runtime-id>' --reason '<actual change>' --input '<operations.json>'
python vaultctl.py checkpoint-context --source codex --session '<id>' --transcript '<actual.jsonl>'
python vaultctl.py checkpoint --source codex --session '<id>' --transcript '<actual.jsonl>' --input '<checkpoint.json>'
python vaultctl.py validate
python vaultctl.py hygiene
python vaultctl.py costs
```

Use `--source claude` for Claude sessions. See the vault's `Vault Workflow Contract.md` for JSON formats and restore. A concurrent hash mismatch requires fresh reads and a rebuilt operation; never overwrite the other writer's edit. Existing daily sessions are immutable.

## Capture and costs

Live capture is primary. Optional draining consumes SessionEnd requests and discovers changed Codex transcripts from the previous seven days after five minutes without transcript changes. Subagent copies and empty sources receive an explicit exclusion record, not a false capture claim. Large sessions remain incremental; unread fragments stay pending.

Retrospective capture needs a logged-in `claude` executable on PATH and a configured `model` in `~/.claude/settings.json`. The command uses `--safe-mode --restricted --permission-mode dontAsk`, read-only `Read,Glob,Grep` tools, `--strict-mcp-config`, `--no-chrome`, `--disable-slash-commands`, `--no-session-persistence`, and structured stream JSON. Check `claude --help` on the target machine for these flags. An unsupported version leaves work pending; do not weaken the restrictions to bypass a failure.

The child receives source evidence over stdin, runs with the vault as its working directory, and has a 15-minute timeout. Its actual returned model supplies attribution. Reported input/output/cache usage and estimated cost enter `state-v2/outcomes.jsonl`; unknown values remain null. Known quota resets delay later launches. `vaultctl.py costs` summarizes these records; it is not a subscription bill.

`already_covered` needs a matching complete daily section; `trivial` needs source evidence and an honest reason. Exit 0, note names, timestamps, unrelated edits, and prose claims cannot certify success. Queue read/journal/replace failures retain pending work.

## Private runtime files

Keep `spool/`, `state-v2/`, queue/batch/incoming JSONL, processed/failed/excluded journals, logs, toggles, lock files, and snapshots out of public source control. The repository ignores the default in-checkout state locations. Custom directories must also be private.

`automation-state.json` with `paused: true` and scope `afk` pauses scheduled jobs; scope `all` also silences live Stop requests. Agent Pulse controls this toggle. Missing means unpaused; unreadable existing state defers scheduled work. It never discards pending requests.

## Optional Windows tasks

Install the controller first and confirm the environment matches its directory. Dry-run both wrappers:

```powershell
$auto = $env:BRAIN_AUTOMATION_DIR
if (-not $auto) { $auto = Join-Path $env:USERPROFILE '.claude\vault-automation' }
powershell -NoProfile -ExecutionPolicy Bypass -File "$auto\drain-queue.ps1" -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File "$auto\nightly-audit.ps1" -DryRun
```

The dry run reports the controller and intended operation. It does not test a live model, actual writes, or user-idle eligibility.

For a new installation, register the following only within the user's approved scheduling scope. If tasks already exist, inspect and merge their definitions rather than replacing them blindly. The drainer runs hourly; audit runs daily with a logon catch-up. Adjust cadence deliberately, then record the actual baseline.

```powershell
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew

$drainAction = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$auto\run-hidden.vbs`" `"$auto\drain-queue.ps1`""
$drainTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName 'VaultQueueDrain' -Action $drainAction -Trigger $drainTrigger -Principal $principal -Settings $taskSettings

$auditAction = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$auto\run-hidden.vbs`" `"$auto\nightly-audit.ps1`""
$auditDaily = New-ScheduledTaskTrigger -Daily -At '03:30'
$auditLogon = New-ScheduledTaskTrigger -AtLogOn -User $user
$auditLogon.Delay = 'PT10M'
Register-ScheduledTask -TaskName 'VaultNightlyAudit' -Action $auditAction -Trigger $auditDaily,$auditLogon -Principal $principal -Settings $taskSettings

# Inspect the installed definitions and hook wiring first, then record that approved state.
python "$auto\vaultctl.py" snapshot-runtime
python "$auto\vaultctl.py" hygiene
```

The baseline is private at `<BRAIN_STATE_DIR>/runtime-contract.json`. Core-only installations do not require a scheduled-task baseline. Runtime checks compare the actual hooks and these two tasks without repairing them. Do not re-record a baseline just to hide unexplained drift.

Both jobs defer with input less than five minutes ago, fullscreen foreground, an unavailable presence probe, or a pause toggle. `-Force` skips only the daily audit stamp. Keep Interactive identity; SYSTEM/S4U cannot observe the user's input session correctly. Keep the VBS launcher to avoid console flashes.

Observe an eligible real run and its receipt/report before claiming scheduled capture works. A deferred run is not a successful capture. Nightly hygiene makes zero model calls and stamps the day only on a verified report. Review `drain.log`, `audit.log`, and `state-v2/hygiene-latest.json`; no process exit alone proves capture.

To disable scheduling, disable only `VaultQueueDrain` and `VaultNightlyAudit` within the user's requested scope. Preserve their definitions and all pending data for a later resume.
