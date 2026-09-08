---
status: active
project: meta
type: guide
updated_by: astra
updated: 2026-09-07
---

# Shared Obsidian Vault Skill

The `obsidian-vault` skill handles retrieval, reconciliation, and checked writing. The `handoff` skill points to [[Handoff Template]]. Detailed mechanics live in [[Vault Workflow Contract]].

Resolve `BRAIN_VAULT_ROOT` and `BRAIN_AUTOMATION_DIR` from the environment, defaulting to `~/Documents/Brain` and `~/.claude/vault-automation`. Both skills belong in each participating client's skills directory. Keep the Claude and Codex `SKILL.md` copies byte-identical; Codex's `agents/openai.yaml` is UI metadata, not a required mirror.

Retrieve through the root map, relevant project index, exact filenames/wikilinks, then headings/body and daily chronology. Fully read selected sources. Current-state claims need actual file/command evidence, not just a recent note. Default searches exclude `.obsidian` and `09 - Archive`; absolute-root searches need `**/` exclusion patterns.

Before writing, inspect the current note/hash and its index, directly relevant links, and today's daily. Commit structured operations through the shared writer. Re-read and rebuild after a conflict. Checkpoint substantive work with actual transcript evidence and verified model attribution; preserve all historical daily entries.

Use `vaultctl.py validate` and `vaultctl.py hygiene` to check schema, indexes, and installed mirrors. Runtime scheduling details belong in [[Vault Autonomy Pipeline]].
