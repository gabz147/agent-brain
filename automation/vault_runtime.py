"""Deterministic, read-only checks of hook wiring and the two vault tasks."""
import json
import os
from pathlib import Path
import subprocess

from vault_core import DEFAULT_STATE, VaultError, atomic_json, now, read_text, sha

BASELINE = DEFAULT_STATE / "runtime-contract.json"
TASK_QUERY = r"""
$ErrorActionPreference = 'Stop'
$items = @()
foreach ($name in @('VaultQueueDrain','VaultNightlyAudit')) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
    $actions = @($task.Actions | ForEach-Object {
        @{ execute=[string]$_.Execute; arguments=[string]$_.Arguments; working_directory=[string]$_.WorkingDirectory }
    })
    $triggers = @($task.Triggers | ForEach-Object {
        @{ type=[string]$_.CimClass.CimClassName; start=[string]$_.StartBoundary; interval=[string]$_.Repetition.Interval;
           duration=[string]$_.Repetition.Duration; delay=[string]$_.Delay; days_interval=[string]$_.DaysInterval; enabled=[bool]$_.Enabled }
    })
    $items += @{ name=$name; actions=$actions; triggers=$triggers; logon_type=[string]$task.Principal.LogonType;
                 enabled=[bool]$task.Settings.Enabled; hidden=[bool]$task.Settings.Hidden; limit=[string]$task.Settings.ExecutionTimeLimit }
}
ConvertTo-Json -InputObject @($items) -Depth 6 -Compress
"""


def runtime_snapshot(home=None):
    home = Path(home or Path.home())
    settings = json.loads(read_text(home / ".claude/settings.json"))
    hook_hash = sha(json.dumps(settings.get("hooks", {}), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", TASK_QUERY]
    process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if process.returncode:
        raise VaultError("Cannot inspect scheduled vault tasks")
    tasks = json.loads(process.stdout)
    return {"hook_sha256": hook_hash, "tasks": tasks}


def write_baseline():
    snapshot = runtime_snapshot()
    atomic_json(BASELINE, {"version": 2, "recorded_at": now().isoformat(), "runtime": snapshot})
    return {"status": "recorded", "path": str(BASELINE), "runtime": snapshot}


def check_runtime():
    if not BASELINE.exists():
        return ["Missing approved runtime baseline"]
    try:
        expected = json.loads(read_text(BASELINE))["runtime"]
        actual = runtime_snapshot()
    except Exception as exc:
        return [str(exc)]
    issues = []
    if actual["hook_sha256"] != expected["hook_sha256"]:
        issues.append("Claude hook wiring differs from the approved baseline")
    expected_tasks = {task["name"]: task for task in expected["tasks"]}
    for task in actual["tasks"]:
        if task != expected_tasks.get(task["name"]):
            issues.append("Scheduled task definition differs: " + task["name"])
        if task["logon_type"] != "Interactive" or not task["hidden"] or not task["enabled"]:
            issues.append("Task no longer satisfies enabled/hidden/Interactive contract: " + task["name"])
    return issues
