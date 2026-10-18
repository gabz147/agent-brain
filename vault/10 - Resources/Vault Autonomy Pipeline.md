---
status: active
project: meta
type: guide
updated_by: human
updated: October 18, 2026 at 12:30:04.613644 PM (UTC-06:00)
---

# Vault Autonomy Pipeline

## Current state

This is a starter runbook. Record the actual installation, enabled components, and verification evidence here after setup. The shipped code supports a shared Python writer and live checkpoints for every installed agent (transcript-bound for Claude and Codex, attested otherwise), with optional extras in the repository's contrib folder; shipping code does not establish that tasks are installed or user acceptance passed. There is no background or retrospective model capture.

The controller uses hashes, OS locks, schema checks, private snapshots, atomic replacement, and read-back. Source receipts bind actual transcript fragments to complete daily sections. Requests, activity indicators, file timestamps, and process exits do not certify capture.

Claude's and Codex's Stop hooks request a live checkpoint after substantive work; other agents checkpoint from their instructions. A session that ends without a checkpoint is not summarized automatically; checkpoint it later from its transcript if needed. The former hourly drain, which ran unattended model captures, was removed because it spent plan usage while the user was away. Nightly hygiene is deterministic and does not invoke a model.

## Operations

Resolve the configured controller directory, then run:

```powershell
python vaultctl.py validate
python vaultctl.py hygiene
```

Use [[Vault Workflow Contract]] for `inspect`, `commit`, `checkpoint-context`, `checkpoint`, and explicit restore. Check the current hash before restoring; preserve receipts during recovery.

Private state lives under `BRAIN_STATE_DIR` and snapshots under `BRAIN_BACKUPS_DIR`. Hooks keep per-session turn logs and gate state there too. If the optional contrib Windows audit is installed, it adds logs, a lock file (`.drain.lock`, name kept for plugin compatibility) and `automation-state.json` beside the controller; the optional Agent Pulse plugin reads those signals, never completion evidence.

## Scheduling constraints

A plain nightly `hygiene --fix` can come from any OS scheduler. If the optional contrib Windows audit is installed instead, `VaultNightlyAudit` uses a hidden VBS launcher and the interactive user's identity. It defers during recent input, fullscreen foreground, unavailable presence probes, or the user's pause toggle. `-Force` bypasses only the daily audit stamp.

With that contrib baseline installed, `snapshot-runtime` records a private comparison baseline after you review the actual task and hook definitions. Do not reset it to hide unexplained drift. A deferred run is not acceptance evidence.

## Verification and acceptance

The repository provides regression tests using temporary vaults and stub processes. After installation, separately verify a real live checkpoint, an eligible scheduled audit if enabled, and manual daily-note creation in an isolated Obsidian vault. Record tested versus user-confirmed outcomes explicitly. Do not copy private transcripts, runtime journals, or snapshots into the public template.

Related: [[Machine Inventory]].
