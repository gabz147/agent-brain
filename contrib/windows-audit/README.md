# Scheduled Windows audit (optional)

A Task Scheduler job that runs the nightly `hygiene` audit with zero model calls, behind interactive idle, fullscreen and pause guards, and `vault_runtime.py`, which records and checks an approved baseline of that task and the vault hooks.

Install Agent Brain first, then copy every file in this folder into the controller folder (`automation_dir` in `~/.agent-brain/config.json`); the scripts expect to sit beside `vaultctl.py`. Dry-run the wrapper:

```powershell
$auto = $env:BRAIN_AUTOMATION_DIR
if (-not $auto) { $auto = (Get-Content (Join-Path $env:USERPROFILE '.agent-brain\config.json') | ConvertFrom-Json).automation_dir }
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

The baseline is private at `<BRAIN_STATE_DIR>/runtime-contract.json`. Core-only installations do not require a scheduled-task baseline. Runtime checks compare the actual hooks and this task without repairing them. After upgrading from a release with the drain, remove `VaultQueueDrain` and re-record the baseline once, since the approved runtime changed. The release that replaced the Node Stop launcher and added the SessionStart hook also changed the approved hook wiring; inspect the new settings, then re-record once. Do not re-record a baseline just to hide unexplained drift.

The audit defers with input less than five minutes ago, fullscreen foreground, an unavailable presence probe, or a pause toggle. `-Force` skips only the daily audit stamp. Keep Interactive identity; SYSTEM/S4U cannot observe the user's input session correctly. Keep the VBS launcher to avoid console flashes.

Nightly hygiene makes zero model calls and stamps the day only on a verified report. `hygiene` records `state-v2/hygiene-latest.json` and an outcomes row even without `--fix`; only `--fix` edits notes. Review `audit.log` and `state-v2/hygiene-latest.json`; no process exit alone proves success.

To disable scheduling, disable only `VaultNightlyAudit` within the user's requested scope.
