---
status: active
project: meta
type: guide
updated_by: astra
updated: 2026-09-15
---

# Shared Obsidian Vault Skill

The `obsidian-vault` skill handles retrieval, reconciliation, and checked writing. The `handoff` skill points to [[Handoff Template]]. The `source-to-vault` skill turns supplied documents into source-cited notes through the same shared writer. Detailed mechanics live in [[Vault Workflow Contract]].

Resolve `BRAIN_VAULT_ROOT` and `BRAIN_AUTOMATION_DIR` from the environment, defaulting to `~/Documents/Brain` and `~/.claude/vault-automation`. All three skills belong in each participating client's skills directory. Keep the Claude and Codex `SKILL.md` copies byte-identical; Codex's `agents/openai.yaml` is UI metadata, not a required mirror.

Follow the boot file's on-demand loading policy. Retrieve through the root map and relevant project index, exact filenames/wikilinks, then headings/body. Load priorities only for relevant status/continuation; use daily Open/Index and matching sessions only when chronology is needed. Fully read selected sources and explicitly requested full reviews. Current-state claims need actual file/command evidence, not just a recent note. Default searches exclude `.obsidian` and `09 - Archive`; absolute-root searches need `**/` exclusion patterns.

Before writing, load the contract's Read and reconcile section and the applicable sections it names. Inspect the current note/hash, its index and directly relevant links. For daily appends, inspect Open/Index and relevant sessions; the controller reads and preserves the full file. Commit structured operations through the shared writer. Re-read and rebuild after a conflict. Checkpoint substantive work with actual transcript evidence and verified model attribution; preserve all historical daily entries.

Use `vaultctl.py validate` and `vaultctl.py hygiene` to check schema, indexes, and installed mirrors. Runtime scheduling details belong in [[Vault Autonomy Pipeline]].

For supplied documents, preserve the original in the user's project folder and run the source-to-vault helper there. It produces hash-addressed original/extraction packets outside Brain. Text and DOCX use Python's standard library; PDF requires PyMuPDF. Inspect complete sources and meaningful page visuals; extraction does not establish semantic completeness. Cite real page/paragraph headings, verify citations, retain changed-source provenance and state unsupported answers. All note writes still use the shared controller. No secondary memory database or external vault index is needed.
