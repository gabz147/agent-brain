---
status: active
project: meta
type: reference
updated_by: astra
updated: 2026-09-07
---

# Machine Inventory

Record what is actually installed, scheduled, hooked, and listening on this machine. The rows below describe the template's optional components, not verified installation. Fill them in during setup. Deterministic hygiene compares installed task/hook definitions against a separately reviewed private runtime baseline and reports differences in its output and `state-v2/hygiene-latest.json`.

## Hardware and OS

- _[OS and version, display, GPU, anything an agent needs to know before touching drivers or performance.]_

## Scheduled tasks (user-created)

| Task | Trigger | Action | Owner note |
|---|---|---|---|
| `VaultNightlyAudit` (optional) | 03:30 daily + logon delayed 10 minutes | `wscript.exe run-hidden.vbs nightly-audit.ps1` | [[Vault Autonomy Pipeline]] |

## Agent hooks

When installed, registered in `~/.claude/settings.json`:

| Event | Hook | Purpose |
|---|---|---|
| PostToolUse Write/Edit/MultiEdit | `hooks/vault/validate-vault-frontmatter.py` | vault schema guard (exit 2 on violation) |
| Stop (asyncRewake) | `hooks/vault/stop-vault-gate.js` | live vault checkpoint |

_[Add the rest of your hooks, MCP servers, and skills of note.]_ Codex uses live controller checkpoints directly. There is no background capture; checkpoint an interrupted session from its transcript before the client's transcript-retention interval expires.

## Obsidian

- Vault: `BRAIN_VAULT_ROOT`. Optional community plugin `agent-pulse` provides the status orb, automation toggle, and soft refresh.
- Manual Daily Notes: monthly date path and dedicated human template; record real UI verification after setup.

## Ports

| Port | Owner | Note |
|---|---|---|
| _[port]_ | _[process]_ | _[why it matters]_ |

## Automation control files

`BRAIN_AUTOMATION_DIR`: `stop-state.json` (activity feed, never completion evidence), `automation-state.json` (pause toggle), deferral state, `.drain.lock` (audit lock; name kept for plugin compatibility), daily audit stamp, and logs. Queue/spool files and journals from releases with the retired drain can be deleted.

`BRAIN_STATE_DIR` defaults to `<automation>/state-v2`: source receipts, live acknowledgments, loop guards, proposals, outcomes, hygiene reports, quota backoff, and the optional runtime baseline. `BRAIN_BACKUPS_DIR` holds private before/after snapshots. These directories are operational records, not a parallel memory database, and must not be published.
