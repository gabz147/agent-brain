---
name: obsidian-vault
description: "Search, recall, continue, audit or update the user's shared Obsidian vault. Use for prior decisions, priorities, project history, related notes, daily checkpoints and handoffs."
---

# Shared Obsidian Vault

`<BRAIN_VAULT_ROOT>` and `<BRAIN_AUTOMATION_DIR>` are the paths your boot rules resolve; `vaultctl.py` is the controller in the automation dir, run with the configured Python. Angle-bracket paths are placeholders, not literal directories. The boot's loading policy and guarantees apply; `10 - Resources/Vault Workflow Contract.md` holds write mechanics.

## Retrieve

Classify recall, status, continue, relate or write. Start with filenames, relevant folder index/topic, then exact wikilinks/backlinks, headings and body; recency breaks ties. Exclude `.obsidian` and Archive by default; expand when history is requested or active retrieval misses. A search hit or navigation extract is a locator, not evidence of a complete read; fully read selected evidence and anything requested for full review. Machine facts live in Machine Inventory. Preserve dated disagreements until evidence resolves them. Cite exact notes/headings.

Search in two steps: rank first, then read the chosen note.

```text
vaultctl.py find "<term>" "<second term>"    ranked live notes with matching lines; no daily notes, no Archive
vaultctl.py find --daily "<term>"            daily notes only, for chronology
vaultctl.py find --archive "<term>"          Archive too
```

Each argument is one term or quoted phrase; ranking is filename, then headings, links and body. A grep tool works the same way: list or count matching files first, excluding `**/.obsidian/**`, `**/09 - Archive/**` and `**/01 - Daily Notes/**`, then show content from one chosen note. For chronology, open `vaultctl.py daily-context <daily-path>` on the matching days and read only the matching sessions fully.

- **Status:** the `[[<Project>` line in `Active Priorities.md`, then the project's current handoff; verify actual state before acting.
- **Continue after several sessions:** `vaultctl.py consolidate-context --note <Project>` lists that project's sessions since its handoff date; read only those sessions.
- **Ledgers:** a Decisions row is one line: search the topic, the `[[<Project>` link and `| locked`. Dead Ends: list its `## ` headings, then read the matching section. Read a whole ledger only for a requested full review or before superseding a row.

Log each real retrieval miss as a new question in `10 - Resources/Recall Eval.md`; `vaultctl.py recall-eval` scores the ranking `find` returns. Facts marked `(as of <date>)` older than 90 days are unverified (`vaultctl.py fact-freshness`). Read `10 - Resources/Vault Actions.md` only for link audits, inbox triage, next-action selection or evidence freshness.

## Write

Only the controller writes notes: `inspect --hash`, then a native read, then `commit` with the operations in a JSON file, as the Contract's Shared writer section specifies. A file-tool write to a vault note is refused where the write guard is installed. Run `validate` after a repair.

Checkpoint substantive work in one call, even without code changes:

```text
vaultctl.py checkpoint --summary --source <agent> --session <id> --transcript "<path>" --topic 'What this was' --done 'Verified outcome' --next 'What remains' --touched '[[Note]]'
```

The session start line gives this session's `--source`, `--session` and `--transcript`. With no transcript, or on "No human-origin turn boundary", replace `--transcript` with `--model <runtime model id>` for an attested receipt. Repeat `--done`; add `--decision`, `--open` (replaces the Open line) and `--profile` (only a fact the user stated about themselves). Single-quote each value; text holding quotes, note operations or several days go in a JSON file with `--input`. Use `--trivial '<reason>'` when nothing is durable. Verify the printed receipt. A daily-only or trivial checkpoint needs only the Contract's Daily checkpoints and coverage section; topic or ledger edits add Shared writer and Related notes and ledgers.

Topic and handoff edits replace current state; history stays in the daily session. A report (audit, review, write-up) carries under its title the byline `vaultctl.py stamp --model <runtime model id>` prints. Handoffs: `10 - Resources/Handoff Template.md`. A repeated task gets one Job note from `10 - Resources/Templates/Job Template.md`; fold corrections into its Lessons. Documents to ingest or answer from: the `source-to-vault` skill.
