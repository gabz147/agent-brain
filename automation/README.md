# Shared controller and optional Windows audit

The Python controller is required for live vault writes and checkpoints. The PowerShell runner and its Task Scheduler job are optional. Nothing in this package starts a model call on its own: checkpoints are written live by the agent inside its own session.

## Components

| Files | Purpose |
|---|---|
| `vaultctl.py`, `vault_core.py`, `vault-schema.json` | Shared CLI, schema, containment, locks, snapshots, atomic commits, and exact-byte restore |
| `vault_sources.py` | Claude/Codex transcript fragments, real model attribution, and source-bound coverage |
| `vault_capture.py` | Validates checkpoint proposals and records source-bound receipts; controller alone writes |
| `vault_hooks.py` | Live Stop decision logic; a request never claims capture |
| `vault_hygiene.py`, `vault_runtime.py` | Deterministic schema/index/priority checks, boot/skill parity, and approved runtime drift checks |
| `invoke-vault-job.ps1`, `nightly-audit.ps1` | Guarded scheduled audit entry point; only verified audit results advance the day stamp |
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

## Checkpoints and costs

Capture is live only. The agent writes each checkpoint in its own session through `checkpoint`; there is no background, scheduled or retrospective model capture. The earlier hourly drain (`VaultQueueDrain`, `drain-queue.ps1`, `vault_queue.py` and the SessionEnd enqueue hook) was removed because it spent the user's plan usage on unattended model runs while they were away. A session that ends without a checkpoint is not summarized automatically; checkpoint it later from its transcript if needed.

`already_covered` needs a matching complete daily section; `trivial` needs source evidence and an honest reason. Exit 0, note names, timestamps, unrelated edits, and prose claims cannot certify success. `vaultctl.py costs` summarizes any historical capture records in `state-v2/outcomes.jsonl`; it is not a subscription bill.

Upgrading from a release with the drain: the installer removes the retired SessionEnd hook entry. Remove an existing `VaultQueueDrain` task yourself (`Unregister-ScheduledTask -TaskName VaultQueueDrain`); left in place it can no longer start a model and only logs an error. Leftover queue/spool files can be deleted.

## Private runtime files

Keep `state-v2/`, any legacy queue/spool files and journals, logs, toggles, lock files, and snapshots out of public source control. The repository ignores the default in-checkout state locations. Custom directories must also be private.

`automation-state.json` with `paused: true` and scope `afk` pauses the scheduled audit; scope `all` also silences live Stop requests. Agent Pulse controls this toggle. Missing means unpaused; unreadable existing state defers scheduled work. It never discards data.

## Optional Windows audit task

Install the controller first and confirm the environment matches its directory. Dry-run the wrapper:

```powershell
$auto = $env:BRAIN_AUTOMATION_DIR
if (-not $auto) { $auto = Join-Path $env:USERPROFILE '.claude\vault-automation' }
powershell -NoProfile -ExecutionPolicy Bypass -File "$auto\nightly-audit.ps1" -DryRun
```

The dry run reports the controller and intended operation. It does not test actual writes or user-idle eligibility.

For a new installation, register the following only within the user's approved scheduling scope. If the task already exists, inspect and merge its definition rather than replacing it blindly. The audit runs daily with a logon catch-up and never calls a model. Adjust cadence deliberately, then record the actual baseline.

```powershell
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$taskSettings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew

$auditAction = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$auto\run-hidden.vbs`" `"$auto\nightly-audit.ps1`""
$auditDaily = New-ScheduledTaskTrigger -Daily -At '03:30'
$auditLogon = New-ScheduledTaskTrigger -AtLogOn -User $user
$auditLogon.Delay = 'PT10M'
Register-ScheduledTask -TaskName 'VaultNightlyAudit' -Action $auditAction -Trigger $auditDaily,$auditLogon -Principal $principal -Settings $taskSettings

# Inspect the installed definitions and hook wiring first, then record that approved state.
python "$auto\vaultctl.py" snapshot-runtime
python "$auto\vaultctl.py" hygiene
```

The baseline is private at `<BRAIN_STATE_DIR>/runtime-contract.json`. Core-only installations do not require a scheduled-task baseline. Runtime checks compare the actual hooks and this task without repairing them. After upgrading from a release with the drain, remove `VaultQueueDrain` and re-record the baseline once, since the approved runtime changed. Do not re-record a baseline just to hide unexplained drift.

The audit defers with input less than five minutes ago, fullscreen foreground, an unavailable presence probe, or a pause toggle. `-Force` skips only the daily audit stamp. Keep Interactive identity; SYSTEM/S4U cannot observe the user's input session correctly. Keep the VBS launcher to avoid console flashes.

Nightly hygiene makes zero model calls and stamps the day only on a verified report. Review `audit.log` and `state-v2/hygiene-latest.json`; no process exit alone proves success.

To disable scheduling, disable only `VaultNightlyAudit` within the user's requested scope.

## Readable note timestamps

New writes use `September 23, 2026 at 6:20:14 AM (UTC-06:00)`. Legacy ISO timestamps and date-only notes stay valid. To reformat existing ISO metadata, preview with `python vaultctl.py format-times`, then apply with `python vaultctl.py format-times --apply`. Use `python3` on macOS/Linux. This changes only the `updated` representation: original times, offsets, authors and all note bodies remain unchanged. Hash checks, private snapshots and daily-history protection still apply. It skips date-only notes and frozen archives. Operational JSON receipts keep ISO timestamps for machine use.
