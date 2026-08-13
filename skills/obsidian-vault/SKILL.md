---
name: obsidian-vault
description: 'Search, recall, continue, audit, or change notes in the shared Obsidian vault — the cross-agent handoff memory. Use for prior decisions, current priorities, project history, related notes, daily notes, or any vault edit.'
---

# Shared Obsidian Vault

Vault-specific procedure for the Obsidian vault at your configured vault root (`BRAIN_VAULT_ROOT`, e.g. `~/Documents/Brain`). The always-loaded boot file (`CLAUDE.md`) and `VAULT-INDEX.md` are the authorities; this skill does not restate their rules. On conflict, follow the authority. If `VAULT-INDEX.md` was not read this session, or context was compacted, read it in full before continuing.

The Markdown vault is the sole shared memory and handoff source for every agent that works here. Do not build a parallel memory store or replace source notes with generated summaries.

## Route the request

Classify before searching. A request to find, explain, review, report, or audit does not authorize a vault edit — keep read-only requests read-only.

- **Recall** — a fact, decision, rationale, prior failure, or working method.
- **Status** — what is open, done, blocked, or stale; verify the underlying note or real system state before calling it current.
- **Continue** — restore the smallest sufficient project context; name the next concrete action.
- **Relate** — backlinks, dependencies, contradictions, notes to reconcile.
- **Write** — create, update, move, rename, archive, or checkpoint, within authorized scope only.

## Retrieval workflow

Start high (identity, rules, system map → `VAULT-INDEX.md` + boot file), descend to project context (`Active Priorities.md`, the folder index, the main project note), then to specific facts (headings, linked notes), then to chronology (daily notes). Descend only as far as the request needs; return to the source note before asserting a fact.

1. Start at `VAULT-INDEX.md`; use its folder map to pick the likely project. For status or continuation, read `Active Priorities.md`, then verify the project's actual state.
2. Search filenames first (`rg --files`), then exact note names and `[[wikilinks]]`, then headings and body. Exclude `.obsidian/` and non-Markdown. Exclude the Archive folder unless the request is historical, names archived work, or the active-note search misses.
3. Rank: exact filename → exact wikilink/backlink → heading → body → recency (tiebreaker only, never over a stronger match).
4. Fully read each selected note before relying on it — start with the best 3–5, expand through direct wikilinks as needed.
5. On conflicting evidence, use daily notes for chronology; if it still conflicts, preserve both claims with their dates and sources — do not silently merge.

```powershell
$vaultRoot = $env:BRAIN_VAULT_ROOT   # e.g. 'C:\Users\<you>\Documents\Brain'
rg --files $vaultRoot -g '*.md' -g '!.obsidian/**' -g '!09 - Archive/**'
rg -n -i --glob '*.md' --glob '!.obsidian/**' --glob '!09 - Archive/**' -- 'search terms' $vaultRoot
rg -n -F --glob '*.md' --glob '!.obsidian/**' --glob '!09 - Archive/**' -- '[[Exact Note Name]]' $vaultRoot
```

## Answer from evidence

- Lead with the result, not the search process.
- Cite the exact note and heading, or a clickable absolute file link.
- Distinguish recorded fact, verified current state, and inference.
- If the vault does not establish an answer, say so — do not fill gaps from memory.
- For continuation: current state, locked decisions, unresolved work, next action.

## Write workflow

1. Read the full target note, its folder index, directly relevant cross-referenced notes, and today's daily note immediately before editing.
2. Append to an existing logical home before creating a note. Preserve unrelated user and agent changes.
3. Edit with the current agent's native targeted mechanism (Codex `apply_patch`; Claude Edit/Write). Never rewrite an existing daily note wholesale.
4. Apply the live frontmatter, wikilink, signature, folder-index, daily-note, rename, move, archive, and profile rules from `VAULT-INDEX.md` and the boot file.
5. When a decision or status changes, update the canonical project note and reconcile `Active Priorities.md` in the same pass — following the lifecycle defined inside `Active Priorities.md`.
6. Update the touched folder's index for a created, renamed, moved, or materially changed note; scan direct backlinks for drift.
7. Append a new signed daily session and Index line; never edit another agent's existing daily session.
8. Self-check the five-key frontmatter schema, links, and signatures; confirm the intended text landed exactly once.

## Boundaries

- Do not upload or index vault content in an external service without explicit approval for that content and service.
- Do not add vector search, embeddings, an LLM proxy, or a second database until measured retrieval failures justify it and the user approves the architecture.

## Mirror (multi-agent setups)

If more than one agent CLI writes to this vault (e.g. Claude Code and Codex), each keeps its own copy of this skill under its own config dir. When authorized to change this skill, edit every copy in one pass, compare SHA-256, and record the change in the shared vault and the day's daily note so the other agent recovers the reason.
