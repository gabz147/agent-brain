---
name: obsidian-vault
description: "Search, recall, continue, audit or update the user's shared Obsidian vault. Use for prior decisions, priorities, project history, related notes, daily checkpoints and handoffs."
---

# Shared Obsidian Vault

Resolve `<BRAIN_VAULT_ROOT>` and `<BRAIN_AUTOMATION_DIR>` from environment variables, defaulting to `~/Documents/Brain` and `~/.claude/vault-automation`. `<HOME>` means the current user home. These are placeholders, not literal paths.

Vault: `<BRAIN_VAULT_ROOT>`. Read `VAULT-INDEX.md` and `10 - Resources/Vault Workflow Contract.md` in full at startup and after compaction. The contract is the single source for schema, model signatures, coordinated writes and capture receipts; the boot files retain critical rules.

## Route and retrieve

Classify recall, status, continue, relate, or write. Recall/review/audit authorizes findings and the required checkpoint, not applying source/config fixes. Authorization already supplied for a concrete change persists.

1. Start with the root index, then the project index/main note. For status/continuation, read Active Priorities and verify real state. Decisions answers allowed/why questions; Dead Ends comes before recurring troubleshooting; Machine Inventory holds machine facts.
2. Search filenames first, then exact wikilinks/backlinks, headings and body. Exclude application internals and Archive unless history is requested or active retrieval misses.
3. Rank exact filename, exact link, heading, body, then recency as a tiebreaker.
4. Fully read selected notes before relying on them. Start with the best few and follow relevant links; do not silently sample a requested full read.
5. Use daily notes for chronology. Preserve dated conflicting claims until evidence resolves them.

```powershell
$vaultRoot = '<BRAIN_VAULT_ROOT>'
rg --files $vaultRoot -g '*.md' -g '!**/.obsidian/**' -g '!**/09 - Archive/**'
rg -n -i -g '*.md' -g '!**/.obsidian/**' -g '!**/09 - Archive/**' -- 'search terms' $vaultRoot
rg -n -F -g '*.md' -g '!**/.obsidian/**' -g '!**/09 - Archive/**' -- '[[Exact Note Name]]' $vaultRoot
```

Lead with the result, cite the exact note/heading or absolute link, and distinguish recorded fact, current verification and inference. Continuation needs current state, locked decisions, remaining work and the next action.

## Write and checkpoint

1. Read the full target, index, relevant linked notes and today's daily note immediately before editing. Consolidate an existing logical home; preserve unrelated changes.
2. Verify the current runtime model. Sign new work as its model label, such as astra or opus 5; never use a client name as a new model signature or infer the actual model from a configured default. Preserve historical signatures.
3. Use `python "<BRAIN_AUTOMATION_DIR>/vaultctl.py" inspect <paths>` for baseline text/hashes. Prepare JSON operations using the native editor, then use `commit --model <verified-runtime-id> --reason <change> --input <json>`. The shared writer validates schema, snapshots, checks concurrent hashes and reads back. Re-read/rebuild on conflict.
4. Update the canonical topic note, stable folder-index entry, and directly affected priorities/ledgers in the same checkpoint. Decisions append; only supersession status/reference may change in an old row. Do not rewrite prior wording.
5. Use `checkpoint-context --source claude|codex --session <actual-id> --transcript <actual-jsonl>`, then `checkpoint` with those arguments and `--input <json>`. Follow the contract's input example. A successful receipt binds the daily append to source evidence and actual model.
6. Existing daily sections and Index entries are immutable. Only insert a new signed Index bullet, append a complete five-section session, update Open for tomorrow, and restamp frontmatter. Correct gaps in a new section. Event-local date/time chooses the note/session; actual write date stamps updated. No whole-file daily replacements.
7. Run `vaultctl.py validate` and verify intended content exactly once. Do not count a hook request, tool call, exit zero or unrelated vault write as a checkpoint.
8. Handoffs use `10 - Resources\Handoff Template.md`, with one current block at the top of the tracking note and a runnable Resume line. Never use OS temp.

A useful audit, decision, or unresolved implementation can warrant capture without code changes. A truly trivial disposition needs a reason and actual source evidence. The unattended backstop handles interruptions but does not replace live checkpoints.

## Boundaries and mirrors

Markdown is canonical. No external upload/index, embeddings, vector store or second knowledge database without explicit approval for that content and design. Operational receipts and private local snapshots are recovery bookkeeping.

Keep this file byte-identical at `<HOME>\.claude\skills\obsidian-vault\SKILL.md` and `<HOME>\.codex\skills\obsidian-vault\SKILL.md`. Compare hashes after authorized changes and record the reason in the shared guide and daily note. Codex's agents/openai.yaml is UI metadata, not a Claude mirror.
