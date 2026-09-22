# Vault Actions

On demand only; no weekly reviews or new schedule. Follow [[Vault Workflow Contract]] for sources and checked writes. [[Home]] displays existing priorities and native topic views.

## Check links

With Node 22+ and Obsidian open on a dedicated `--remote-debugging-port=9333`, run:

```text
node <BRAIN_AUTOMATION_DIR>/vault_links.mjs --vault <BRAIN_VAULT_ROOT>
```

Resolve the placeholders from your environment, defaulting to ~/.claude/vault-automation and ~/Documents/Brain; quote paths with spaces. The checker also honors BRAIN_VAULT_ROOT. It verifies the open vault and completed indexing, using Obsidian's own link parser. Default output is counts plus 20 findings; --json returns the complete report, --port selects a different debug port.

Launch Obsidian with that flag using your normal application executable. If it is already running without the flag, save work and reopen it; never force-close it. Keep a single vault window on that port. No permanent service or external index is required.

Report missing files/blocks, ambiguous names, headings needing review and orphan candidates. Archive is excluded as a source; archived targets can resolve, but their fragments are not inspected. External URLs/files are not fetched. Heading formatting/nesting and intentional orphans need review. Never create stubs, merge/delete notes or rewrite history automatically.

## Triage inbox

Read selected captures completely and locate their existing topic homes. Propose capture, destination, next action and evidence. Reuse notes; no invented deadlines/projects. Consolidate through the shared writer only within the request's scope; preserve source evidence and repair incoming links for authorized moves.

## Choose next action

Read relevant [[Active Priorities]] sections and candidate topic evidence; verify actual state. Return up to three existing actionable items with source, reason and first step. Flag missing input or acceptance. Do not promote waiting/parked work or manufacture tasks.

## Evidence freshness

For volatile facts, use a body table only when needed:

```text
Claim | Source / exact location | Last verified | Assessment | Recheck when
```

Use supported, provisional, contested or unsupported. Verification dates record actual checks; updated is only the note's last write time, not the evidence verification time. Preserve dated contradictions and link originals. Name a meaningful recheck trigger, not a schedule. Keep the existing schema unchanged.
