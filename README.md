# agent-brain

A shared Markdown memory system for Claude Code and Codex. Agents read the same Obsidian vault, keep decisions and project context there, and append verified daily checkpoints that survive sessions and context resets.

This repository is a portable public template. It contains starter notes and reusable workflow code, with no personal vault contents, transcripts, credentials, or runtime history.

## What it does

- Keeps Markdown canonical, with a root map, priorities, project indexes, decisions, and a dead-end ledger.
- Gives both clients one writing contract and mirrored `obsidian-vault` and `handoff` skills.
- Signs new work with its verified runtime model, such as `astra` or `opus 5`, while preserving historical signatures.
- Uses a shared Python writer for schema validation, hash checks, file locking, private before/after snapshots, atomic writes, and read-back.
- Preserves existing daily sessions and Index entries. Corrections become new sessions; only the Open line and frontmatter can be refreshed.
- Binds capture receipts to actual transcript fragments and verified daily sections. A tool call, changed timestamp, or successful process exit cannot prove completion.
- Optionally captures interrupted Claude/Codex sessions while the user is away. Nightly hygiene is deterministic and makes no model calls.
- Offers an optional Obsidian status orb, pause toggle, and soft refresh through Agent Pulse.

## Install or upgrade

Follow [INSTALL.md](INSTALL.md). The shared controller in `automation/` is required for both live and scheduled writing. Registering scheduled jobs is optional.

For an existing installation, back up its workflow files, merge the new shared boot blocks and skills, copy the controller and hook adapters, and add the workflow/manual templates without replacing real notes. Regenerate the local runtime baseline only after reviewing the actual hook/task configuration. Old queues remain readable; keep all pending state and receipts.

## Layout

| Path | Contents |
|---|---|
| `boot/` | Claude and Codex boot files with the same critical rules |
| `vault/` | Generic starter vault, workflow contract, and model/manual daily templates |
| `skills/` | Shared vault and durable handoff skills; optional Codex UI metadata |
| `automation/` | Shared controller, schema, capture adapters, regression tests, and optional Windows runners |
| `hooks/vault/` | Claude Stop, SessionEnd, and PostToolUse adapters |
| `settings/` | Hook snippet and manual Obsidian daily-note settings |
| `plugins/agent-pulse/` | Optional desktop Obsidian indicator and pause toggle |
| `templates/` | Reusable model-authored note skeletons |

## Configuration

Set these in the environment of the agent, hooks, Obsidian, and any scheduled tasks. Paths may contain spaces.

| Variable | Default / meaning |
|---|---|
| `BRAIN_VAULT_ROOT` | `~/Documents/Brain` |
| `BRAIN_AUTOMATION_DIR` | Installed controller directory, normally `~/.claude/vault-automation` |
| `BRAIN_STATE_DIR` | `<automation>/state-v2`; private receipts and diagnostics |
| `BRAIN_BACKUPS_DIR` | `<vault parent>/<vault name> Backups/versions`; private snapshots |
| `BRAIN_PYTHON` | Python executable for the Node hook and Windows runner; otherwise `python` on Windows and `python3` for the Node hook elsewhere |

`VAULT_AUTOMATION_DIR` is accepted as a legacy alias when `BRAIN_AUTOMATION_DIR` is unset. `VAULT_AUTOMATION=1` prevents capture children from recursively queueing themselves. Set `BRAIN_AUTOMATION_DIR` consistently with the installed directory, especially when running from a checkout.

The schema accepts any kebab-case project slug. Configure `project_allowlist` and `folder_projects` in `automation/vault-schema.json` if you need a fixed set and folder defaults. The human-readable contract contains a generated schema block checked by hygiene.

`BRAIN_COST_LEDGER` and the old automatic Markdown cost-row appender are retired. `vaultctl.py costs` summarizes actual reported usage, cost, errors, and deferrals from private operational records. Missing values remain unknown.

## Verification

From the checkout:

```powershell
python -m unittest discover -s automation/tests -q
```

The tests use temporary vaults and stub model processes. They cover preservation, conflicts, restore, source attribution, checkpoint replay, durable queues, quota/timeout handling, and portable hooks without paid model calls or live-vault writes.

The Python core and hook adapters support platforms with Python 3.10+ and Node.js. Scheduled runners and runtime task inspection require Windows, PowerShell, and Task Scheduler. The capture child requires an authenticated Claude CLI supporting the restricted flags listed in [automation/README.md](automation/README.md). Source formats and CLI behavior can change; run the installation smoke checks for your version.

See [LICENSE](LICENSE).
