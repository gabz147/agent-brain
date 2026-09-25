---
status: active
project: meta
type: guide
updated_by: astra
updated: 2026-09-07
---

# Vault Autonomy Pipeline

## Current state

This is a starter runbook. Record the actual installation, enabled components, and verification evidence here after setup. The shipped code supports a shared Python writer, live Claude/Codex checkpoints, and an optional Windows audit task; shipping code does not establish that tasks are installed or user acceptance passed. There is no background or retrospective model capture.

The controller uses hashes, OS locks, schema checks, private snapshots, atomic replacement, and read-back. Source receipts bind actual transcript fragments to complete daily sections. Requests, activity indicators, file timestamps, and process exits do not certify capture.

Claude's Stop adapter requests a live checkpoint; Codex checkpoints directly. A session that ends without a checkpoint is not summarized automatically; checkpoint it later from its transcript if needed. The former hourly drain, which ran unattended model captures, was removed because it spent plan usage while the user was away. Nightly hygiene is deterministic and does not invoke a model.

## Operations

Resolve the configured controller directory, then run:

```powershell
python vaultctl.py validate
python vaultctl.py hygiene
python vaultctl.py costs
```

Use [[Vault Workflow Contract]] for `inspect`, `commit`, `checkpoint-context`, `checkpoint`, and explicit restore. Check the current hash before restoring; preserve receipts during recovery.

Private state lives under `BRAIN_STATE_DIR` and snapshots under `BRAIN_BACKUPS_DIR`. The scheduled audit wrapper additionally uses logs, a lock file (`.drain.lock`, name kept for plugin compatibility) and `automation-state.json` beside the installed controller. Agent Pulse reads compatible activity signals, never completion evidence.

## Scheduling constraints

If installed, `VaultNightlyAudit` uses a hidden VBS launcher and the interactive user's identity. It defers during recent input, fullscreen foreground, unavailable presence probes, or the user's pause toggle. `-Force` bypasses only the daily audit stamp.

After reviewing actual task/hook definitions, `snapshot-runtime` records a private comparison baseline. Do not reset it to hide unexplained drift. A deferred run is not acceptance evidence.

## Verification and acceptance

The repository provides regression tests using temporary vaults and stub processes. After installation, separately verify a real live checkpoint, an eligible scheduled audit if enabled, and manual daily-note creation in an isolated Obsidian vault. Record tested versus user-confirmed outcomes explicitly. Do not copy private transcripts, runtime journals, or snapshots into the public template.

Related: [[Shared Obsidian Vault Skill]], [[Automation Costs]], [[Machine Inventory]].
