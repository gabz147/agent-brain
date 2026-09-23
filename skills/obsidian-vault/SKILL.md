---
name: obsidian-vault
description: "Search, recall, continue, audit or update the user's shared Obsidian vault. Use for prior decisions, priorities, project history, related notes, daily checkpoints and handoffs."
---
# Shared Obsidian Vault

Resolve `<BRAIN_VAULT_ROOT>` and `<BRAIN_AUTOMATION_DIR>` from the environment, defaulting to `~/Documents/Brain` and `~/.claude/vault-automation`. Use `BRAIN_PYTHON`, otherwise `python3` on macOS/Linux or `python` on Windows. Angle-bracket paths are placeholders, not literal directories.

Vault: `<BRAIN_VAULT_ROOT>`. Follow the boot's task-based loading policy. No blanket startup/compaction bundle. `VAULT-INDEX.md` routes project work; `10 - Resources/Vault Workflow Contract.md` defines writing mechanics and safeguards, loaded as needed before writes.

## Retrieve

Classify recall, status, continue, relate or write. Start with filenames, relevant folder index/topic, then exact wikilinks/backlinks, headings and body; recency breaks ties. Exclude `.obsidian` and Archive by default; expand when history is requested or active retrieval misses. Fully read selected evidence and anything requested for full review. A search hit or navigation extract is a locator, not evidence of a complete read.

Status/continuation loads relevant priorities and the project's current handoff, then verifies actual state. If the project is unclear, inspect the queue or clarify. Check Decisions before potential conflicts, Dead Ends before recurring troubleshooting; Machine Inventory holds machine facts. Daily chronology is conditional: start with Open/session headings, then read matching sessions completely. Preserve dated disagreements until evidence resolves them. Cite exact notes/headings; distinguish recorded facts, verification and inference.

```powershell
$vaultRoot = '<BRAIN_VAULT_ROOT>'
rg --files $vaultRoot -g '*.md' -g '!**/.obsidian/**' -g '!**/09 - Archive/**'
rg -n -i -g '*.md' -g '!**/.obsidian/**' -g '!**/09 - Archive/**' -- 'search terms' $vaultRoot
```

Read `10 - Resources/Vault Actions.md` only for link audits, inbox triage, next-action selection or evidence freshness. Existing vaults without that note can use this skill's `references/vault-actions.md`. No weekly reviews.

## Write and checkpoint

Read applicable contract sections before writing; inspect full target/topic/index and relevant linked evidence. For a routine append, use `daily-context <daily-path>` instead of loading the entire daily log; read matching historical sessions if coverage or conflicts are uncertain. The shared writer independently checks all existing daily bytes. Never use this exception to substitute an excerpt for a requested full review.

Use `python "<BRAIN_AUTOMATION_DIR>/vaultctl.py"`: `inspect` for current text/hash, `commit` for checked operations, `checkpoint-context` for verified model/event time/source boundary, then `checkpoint --summary` with the same source/session/transcript and prepared JSON. The writer automatically stamps `updated` with readable local date, 12-hour time, seconds and timezone; never invent a historical time. Full receipts remain on disk. Re-read/rebuild after conflict; verify intended content and source-bound completion. Validate after changes; avoid repeating whole-vault reads or unchanged tool output.

Consolidate the topic and stable index description, update only affected priorities/ledgers, and append the five-section daily session. Preserve all historical bytes/signatures and the five-key schema. No source/config fixes without existing authorization; audits authorize findings and their checkpoint. Substantive work needs capture even without code changes; backstops cover interruptions. Handoffs follow `10 - Resources/Handoff Template.md`, never OS temp.

Markdown remains canonical; no external upload/index, embeddings or parallel knowledge database without explicit approval. Operational receipts/private snapshots are recovery bookkeeping. When both clients participate, keep this skill byte-identical in `.claude/skills/obsidian-vault` and `.codex/skills/obsidian-vault`; check parity after changes. Codex agents/openai.yaml is UI metadata, not a Claude mirror.
