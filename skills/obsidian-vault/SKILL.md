---
name: obsidian-vault
description: "Search, recall, continue, audit or update the user's shared Obsidian vault. Use for prior decisions, priorities, project history, related notes, daily checkpoints and handoffs."
---
# Shared Obsidian Vault

Resolve `<BRAIN_VAULT_ROOT>` and `<BRAIN_AUTOMATION_DIR>` from the environment, else from `~/.agent-brain/config.json` (`vault_root`, `automation_dir`), defaulting to `~/Documents/Brain` and `~/.agent-brain/automation`. Use `BRAIN_PYTHON`, otherwise `python3` on macOS/Linux or `python` on Windows. Angle-bracket paths are placeholders, not literal directories. The boot's loading policy and guarantees apply; `10 - Resources/Vault Workflow Contract.md` holds write mechanics.

## Retrieve

Classify recall, status, continue, relate or write. Start with filenames, relevant folder index/topic, then exact wikilinks/backlinks, headings and body; recency breaks ties. Exclude `.obsidian` and Archive by default; expand when history is requested or active retrieval misses. A search hit or navigation extract is a locator, not evidence of a complete read; fully read selected evidence and anything requested for full review. Machine facts live in Machine Inventory. Preserve dated disagreements until evidence resolves them. Cite exact notes/headings.

Search in two steps: list or count first, then read capped lines from one chosen note. Daily notes are searched only for chronology.

```powershell
$vaultRoot = '<BRAIN_VAULT_ROOT>'
rg --files $vaultRoot -g '*.md' -g '!**/.obsidian/**' -g '!**/09 - Archive/**' -g '!**/01 - Daily Notes/**'
rg -c -i -g '*.md' -g '!**/.obsidian/**' -g '!**/09 - Archive/**' -g '!**/01 - Daily Notes/**' -- 'terms' $vaultRoot
rg -n -i -M 300 --max-columns-preview -m 5 -- 'terms' '<note.md>'
rg -c -i -- 'terms' "$vaultRoot/01 - Daily Notes"
```

With a grep tool, list matching files or counts first and show content only for one chosen note with a line limit. For chronology, open `vaultctl.py daily-context <daily-path>` on the matching days and read only the matching sessions fully.

- **Status:** `rg -n -F '[[<Project>' 'Active Priorities.md'`, then the project's current handoff; verify actual state before acting.
- **Continue after several sessions:** `vaultctl.py consolidate-context --note <Project>` lists that project's sessions since its handoff date; read only those sessions.
- **Ledgers:** check Decisions with `rg -n -i -e '<topic>' -e '[[<Project>' -e '\| locked' Decisions.md` (each row is one line); check Dead Ends with `rg -n '^## ' 'Dead Ends.md'`, then the matching section, or `rg -n -i -m 8 '<term>' 'Dead Ends.md'`. Read a whole ledger only for a requested full review or before superseding a row.

Log each real retrieval miss as a new question in `10 - Resources/Recall Eval.md`. Facts marked `(as of <date>)` older than 90 days are unverified (`vaultctl.py fact-freshness`). Read `10 - Resources/Vault Actions.md` only for link audits, inbox triage, next-action selection or evidence freshness; vaults without it can use this skill's `references/vault-actions.md`.

Optional, with Obsidian 1.12.7+ and its command line interface enabled: `python "<BRAIN_AUTOMATION_DIR>/obsidian_read.py"` (`diagnostics`, `link-audit`, `backlinks`, `properties`, `history`, `preflight`); Obsidian must be running. Rules: the Contract's Read-only Obsidian CLI section. If the CLI is unavailable, continue normally.

## Write

Use `python "<BRAIN_AUTOMATION_DIR>/vaultctl.py"` as the Contract specifies: `inspect --hash`, then a native read, before `commit`; one `checkpoint --summary` call per checkpoint, from the transcript (claude, codex) or with `--source <agent> --model <id>` and the summary flags (`--topic`, `--done`, `--next`, `--decision`, `--touched`, `--open`); `--trivial "<reason>"` when nothing is durable; `validate`. A daily-only or trivial checkpoint needs only its Daily checkpoints and coverage section; topic or ledger edits add Shared writer and Related notes and ledgers. Topic and handoff edits replace current state; history stays in the daily session. Substantive work needs capture even without code changes. Handoffs: `10 - Resources/Handoff Template.md`. A repeated task gets one Job note from `10 - Resources/Templates/Job Template.md`; fold corrections into its Lessons. Documents to ingest or answer from: the `source-to-vault` skill.
