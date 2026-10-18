# Vault Actions

On demand only; no weekly reviews or new schedule. Follow [[Vault Workflow Contract]] for sources and checked writes. [[Home]] displays existing priorities and native topic views.

## Check links

Run the built-in read-only audit; it needs only Python:

```text
python <BRAIN_AUTOMATION_DIR>/vaultctl.py links
```

Resolve the placeholder from your environment or ~/.agent-brain/config.json, defaulting to ~/.agent-brain/automation (older installs: ~/.claude/vault-automation); `brain links` does the same. Default output is counts plus 20 findings per kind; --full returns everything. It reports missing targets, ambiguous names (with the file Obsidian would pick), unmatched headings or blocks, and orphan candidates in folders 02-07 and 10. Archive is excluded as a source; archived targets can resolve.

For Obsidian's own resolution, the native CLI (Obsidian 1.12.7+) gives a quick file-link view without a debug port: `python <BRAIN_AUTOMATION_DIR>/obsidian_read.py link-audit` or `backlinks "<vault-relative.md>"`. The debug-port checker that uses Obsidian's parser for headings and blocks is optional, in the repository's contrib/obsidian-links.

Report findings for review: external URLs/files are not fetched, heading formatting and intentional orphans need judgment. Never create stubs, merge/delete notes or rewrite history automatically.

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
