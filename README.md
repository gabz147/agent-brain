# agent-brain

A portable **memory system for AI coding agents** built on a plain Obsidian (Markdown) vault. It gives Claude Code — or any agent that can read/write files — a persistent, self-maintaining memory that survives context compaction, hands off cleanly between sessions and between different agents, and boots the same "colleague" every time.

This is the reusable, sanitized template extracted from a working personal setup. Clone it, run the install, fill in your specifics.

## What it gives you

- **One source of truth.** A Markdown vault the agent reads at the start of every session (`VAULT-INDEX.md` → `Active Priorities.md` → project notes → daily logs). No vector DB, no separate memory service — just files you can also open in Obsidian and read yourself.
- **Identity that survives compaction.** A boot file (`CLAUDE.md`) the harness auto-loads and re-reads after compaction, holding who the agent is and the rules that can't lapse.
- **Enforced structure.** A PostToolUse hook rejects any note whose frontmatter breaks the five-key schema, so the vault never rots into inconsistency.
- **Automatic checkpointing.** A Stop hook notices when a turn did real work and prompts the agent to write it into the daily note before moving on.
- **Multi-agent handoff.** Every entry is signed (`claude` / `codex` / `human`), so two agents can share one vault without stepping on each other.
- **Two root ledgers.** `Decisions.md` (every deliberate choice, with a locked/active/superseded status, so an agent can check "does this contradict something we decided?") and `Dead Ends.md` (what was tried, why it failed, what to do instead — searched before inventing an approach).
- **A daily note with one mutable line.** `**Open for tomorrow:**` under the date heading is rewritten by whichever session ends last; the next session reads it first. Everything else in a daily note is append-only.
- **Optional self-population.** A Windows automation layer turns finished sessions into daily notes and runs a nightly audit that fixes drift — fully hands-off. It verifies that each headless run actually wrote something (exit 0 is never trusted), logs deferrals once per streak, and appends a row per run to an `Automation Costs.md` ledger so the token burn is measurable.
- **Optional live indicator + kill switch.** A small Obsidian plugin (`plugins/agent-pulse`) shows a status orb for whether an agent is working in the vault, queue depth and last drain in its tooltip, a click-to-toggle that pauses the automation (AFK jobs only, or everything including the live checkpoint) when you don't want tokens spent, and a soft-refresh button that picks up agent edits without a jarring full reload.

## Repo layout

```
boot/            CLAUDE.md (+ AGENTS.md) — the always-loaded boot config / identity / rules
vault/           the starter vault: VAULT-INDEX.md, Active Priorities.md, Decisions.md, Dead Ends.md,
                 Automation Costs.md, Machine Inventory.md, folder skeleton, daily-note + handoff templates
templates/       DAILY-NOTE.md, FOLDER-INDEX.md, NOTE.md
skills/          obsidian-vault/ — the retrieval + write procedure the agent invokes
hooks/vault/     validate-vault-frontmatter.py, stop-vault-gate.js, session-end-enqueue.js
settings/        vault-hooks.snippet.json — the hook wiring to merge into ~/.claude/settings.json
automation/      OPTIONAL Windows self-population layer (drainer + nightly audit + scheduler wiring)
plugins/         OPTIONAL Obsidian plugin (agent-pulse): a status orb + soft-refresh button
INSTALL.md       step-by-step setup, written for an installing agent to execute
```

## Install

Point your agent at **[INSTALL.md](INSTALL.md)** and let it do the setup, or follow it yourself. In short:

1. Copy `vault/` to your vault location; set `BRAIN_VAULT_ROOT`.
2. Copy `boot/CLAUDE.md` → `~/.claude/CLAUDE.md`, `skills/obsidian-vault/` → `~/.claude/skills/`, `hooks/vault/` → `~/.claude/hooks/vault/`.
3. Merge `settings/vault-hooks.snippet.json` into `~/.claude/settings.json`.
4. Verify the hooks fire. (Optional) install the automation module per `automation/README.md`.

## Configuration

Everything machine-specific is driven by two environment variables (with sensible fallbacks):

| Variable | Meaning | Fallback |
|---|---|---|
| `BRAIN_VAULT_ROOT` | absolute path to the vault | `~/Documents/Brain` |
| `BRAIN_AUTOMATION_DIR` | automation/queue dir (only if using automation) | `~/.claude/vault-automation` |
| `BRAIN_COST_LEDGER` | path of the `Automation Costs.md` ledger the scripts append to (only if using automation) | `<vault>/Automation Costs.md` |

The frontmatter validator accepts any kebab-case `project:` slug by default, so your notes are never rejected for a project name it hasn't heard of. Lock it to a fixed set via `PROJECT_ALLOWLIST` in `hooks/vault/validate-vault-frontmatter.py` if you want strictness.

## Notes

- **Your vault is yours.** This template ships only the scaffolding — no personal notes. Keep your real vault private (a private git repo if you version it).
- **Cross-platform core, Windows automation.** The vault, boot file, skill, and the three hooks work anywhere Node + Python run. The `automation/` self-population layer is Windows-only (PowerShell + Task Scheduler).
- **No lock-in.** It's Markdown. Delete the hooks and you still have a readable Obsidian vault.

## License

See [LICENSE](LICENSE).
