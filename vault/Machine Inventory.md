---
status: active
project: meta
type: reference
updated_by: human
updated: 2026-01-01
---

# Machine Inventory

Living inventory of what is installed, scheduled, hooked, and listening on this machine, so an agent answers "what runs at logon", "why is that port busy", "which hooks fire on Write" from one note instead of traversing the disk. Fill it in during setup; the nightly audit (optional module) diffs the **Scheduled tasks** and **Agent hooks** sections against the live machine and reports drift to the Inbox audit note.

## Hardware and OS

- _[OS and version, display, GPU, anything an agent needs to know before touching drivers or performance.]_

## Scheduled tasks (user-created)

| Task | Trigger | Action | Owner note |
|---|---|---|---|
| `VaultDrainQueue` | every 15 min | `wscript run-hidden.vbs drain-queue.ps1` (automation module) | `automation/README.md` |
| `VaultNightlyAudit` | 03:30 daily + at logon | `wscript run-hidden.vbs nightly-audit.ps1` (automation module) | `automation/README.md` |

## Agent hooks

Registered in `~/.claude/settings.json`:

| Event | Hook | Purpose |
|---|---|---|
| PostToolUse Write/Edit/MultiEdit | `hooks/vault/validate-vault-frontmatter.py` | vault schema guard (exit 2 on violation) |
| SessionEnd | `hooks/vault/session-end-enqueue.js` | enqueue the session for the drainer (automation module) |
| Stop (asyncRewake) | `hooks/vault/stop-vault-gate.js` | live vault checkpoint |

_[Add the rest of your hooks, MCP servers, and skills of note.]_ Claude Code deletes session transcripts after 30 days by default (`cleanupPeriodDays`), so any drain backlog must clear before then.

## Obsidian

- Vault: `BRAIN_VAULT_ROOT`. Community plugin `agent-pulse` (status orb, automation toggle, soft refresh).

## Ports

| Port | Owner | Note |
|---|---|---|
| _[port]_ | _[process]_ | _[why it matters]_ |

## Automation control files

`BRAIN_AUTOMATION_DIR`: `queue.jsonl` (pending sessions), `queue.batch.jsonl` (in-flight), `processed.jsonl`, `failed.jsonl`, `stop-state.json` (live-capture guard), `automation-state.json` (your pause toggle, written by Agent Pulse), `deferral-drain.json` / `deferral-audit.json` (current deferral streak), `.drain.lock`, `last-audit-date.txt`, `drain.log`, `audit.log`.
