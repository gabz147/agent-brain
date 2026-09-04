---
status: active
project: meta
type: reference
updated_by: human
updated: 2026-01-01
---

# Decisions

The decision ledger. Every deliberate, cross-session choice lives here in one table so any agent can answer "does this contradict something we already decided?" without knowing which note to open. The boot-file rule **Locked decisions stay locked** points at this file.

## Rules

- **Append a row when a decision is made** in any session — by the user, or by an agent with the user's confirmation. The automation's drainer and the live checkpoint do this too when a transcript contains a decision.
- **Status:** `locked` (changing it needs the user to say so explicitly, in that turn) · `active` (current default, revisable on evidence) · `superseded` (keep the row, add the date and the replacing row's date).
- **Never edit another row's wording.** To change a decision, add a new row and mark the old one `superseded`.
- **Enforced in** names the file or note that makes the decision real. If nothing enforces it, say `convention`.
- One line per row. The reasoning goes in the linked note, not here.

## Ledger

| Date | Decision | Why | Enforced in | Status |
|---|---|---|---|---|
| (setup) | Markdown is canonical. No database, vector store, or embedding layer unless measured retrieval misses justify it and the user approves the design. | Portability, one source of truth, retrieval works at this size. | `skills/obsidian-vault/SKILL.md` Boundaries | locked |
| (setup) | Boot files (`CLAUDE.md`, `AGENTS.md`) live outside the vault. | They survive compaction and keep the vault pure memory. | boot files | locked |
| (setup) | Every automation component fails open: a bug must never block a real session. | A broken guard that blocks is worse than no guard. | `hooks/vault/` | locked |
| (setup) | Never archive a note on the agent's own initiative. | Archiving is the user's call. | `VAULT-INDEX.md` Archiving | locked |
| (setup) | Double-confirm before any source-code, running-config, commit, push, or deploy change. Vault notes are exempt. | Code is read-only by default. | boot files | locked |
| (setup) | Existing daily-note session sections are immutable; append only. `Session N` is a label, never renumbered; the heading's time is the order. The `Open for tomorrow` line is the one mutable line. | Bounds any bad append to one extra section; concurrent writers cannot race on N. | `VAULT-INDEX.md` Daily Notes, `automation/capture-prompt.md` | locked |
| (setup) | Automation success means a verified write or an accepted no-op; a headless child's exit 0 is never trusted on its own. | Sandbox-blocked and rate-limited children exit 0. | `automation/drain-queue.ps1`, `automation/nightly-audit.ps1` | locked |
