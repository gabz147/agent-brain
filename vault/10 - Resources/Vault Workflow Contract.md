---
status: active
project: meta
type: guide
updated_by: astra
updated: 2026-09-07
---

# Vault Workflow Contract

The shared writing and capture contract for [[Claude Code]] and [[Codex]], stored in [[Obsidian]]. [[VAULT-INDEX]] holds the profile and map; [[Active Priorities]] holds open work; [[Decisions]] holds deliberate choices; [[Dead Ends]] holds failed recurring approaches. [[Shared Obsidian Vault Skill]] describes retrieval. [[Vault Autonomy Pipeline]] records implementation and validation.

This portable contract consolidates writing mechanics and model-specific signatures. Installation and later source/configuration changes follow the user's actual authorization; this template grants no blanket approval. This contract replaces duplicated mechanics in the two boot files, skills and capture prompts. Boot files retain a short identical block of critical rules.

## Authorship

Use the actual model that wrote the entry, including when an unattended model summarizes a different client's transcript.

| Runtime evidence | Signature |
|---|---|
| `gpt-6-astra` | `astra` |
| `gpt-5.6-sol` | `sol` |
| `gpt-5.6-terra` | `terra` |
| `gpt-5.6-luna` | `luna` |
| `claude-opus-5` | `opus 5` |
| Other verified runtime ID | Canonical lowercase model label or its exact lowercase ID |
| Runtime model unavailable | `unknown-model`, with the uncertainty stated |
| Deterministic maintenance | `automation` |
| Manual writing | `human` |

Resolve model IDs from trusted runtime metadata, Codex `turn_context.model`, Claude `message.model`, or a child result's actual model usage. A configured model is a launch preference, not evidence of what ran. New model writes cannot use `claude` or `codex`; those remain valid historical signatures.

Four locations carry attribution: frontmatter `updated_by` records the last writing model; new folder-index descriptions and daily Index bullets end with `` `(model)` ``; new session headings end with `` `model` ``. Preserve historical entries and their author tags. When replacing a current index description, sign the replacement with its actual writer; never reattribute an unchanged description. A missing historical tag becomes `unknown-model`, never a guessed model.

## Schema

`<BRAIN_AUTOMATION_DIR>/vault-schema.json` is the machine-readable definition. `vaultctl.py validate` uses it for both clients and scheduled hygiene.

<!-- VAULT SCHEMA START -->
- Required keys: `status`, `project`, `type`, `updated_by`, `updated`.
- Optional existing key: `aliases`. No other keys.
- Status: `active`, `completed`, `parked`, `idea`, `archived`.
- Project: any kebab-case slug; optional project_allowlist in vault-schema.json. Starter values: `example-project`, `personal`, `meta`.
- Type: `index`, `reference`, `guide`, `plan`, `log`.
- Signature: lowercase model label/ID, `human`, `automation`, or `unknown-model`; legacy tags remain valid in history.
- Updated: an actual calendar date in `YYYY-MM-DD`, taken from the system clock at the write.
<!-- VAULT SCHEMA END -->

Infer values from evidence. Starter folder defaults: 02 example-project; 01/08 personal; root/10 meta. Configure folder_projects in the machine schema for actual project folders. Project slugs accept kebab-case unless project_allowlist restricts them. Inbox defaults to personal unless content establishes a project; archive retains its original project. Content wins over folder defaults. Use active for ongoing work, completed only for finished work, idea for a proposal, parked for deliberately quiet work, archived only after authorized archiving.

Types describe document purpose: index maps notes, reference stores lookup material, guide gives a procedure, plan tracks strategy/work, log records events. Every dated daily note is `active/personal/log`.

Code is exempt. Frozen `09 - Archive/Old Memory/` is exempt and read-only. One output-definition exception exists: [[Manual Daily Note Template]] contains `updated_by: human` and the literal `updated: "{{date:YYYY-MM-DD}}"`, because Obsidian expands them into a manual note. Its maintainer is recorded in the snapshot manifest and this contract, rather than falsely labeling generated manual entries as model-written. No ordinary note may use a placeholder date.

## Read and reconcile

Read the full target, its index, directly relevant linked notes and today's daily note immediately before writing. Search filenames first, then exact wikilinks, headings and body. Current claims require source evidence; chronology alone is not proof of current state. Default retrieval excludes application internals and Archive:

```powershell
$vaultRoot = '<BRAIN_VAULT_ROOT>'
rg --files $vaultRoot -g '*.md' -g '!**/.obsidian/**' -g '!**/09 - Archive/**'
rg -n -i -g '*.md' -g '!**/.obsidian/**' -g '!**/09 - Archive/**' -- 'search terms' $vaultRoot
```

A recall/review/audit request authorizes findings and their required daily checkpoint, not applying source/config changes. Preserve relevant disagreements with dates and sources until evidence resolves them. Prefer an existing logical home over creating a note.

## Shared writer

Resolve angle-bracket paths from the environment: BRAIN_VAULT_ROOT defaults to ~/Documents/Brain; BRAIN_AUTOMATION_DIR defaults to ~/.claude/vault-automation; BRAIN_BACKUPS_DIR defaults to a sibling <vault name> Backups/versions directory. Both agents use the same controller:

```powershell
$vaultCtl = '<BRAIN_AUTOMATION_DIR>\vaultctl.py'
python $vaultCtl inspect '02 - Example Project/Example.md'
python $vaultCtl commit --model '<verified-runtime-id>' --reason '<concrete change>' --input '<prepared-json-path>'
python $vaultCtl validate
```

A commit input is `{"operations":[...]}`. Each operation has a vault-relative `path`, `expected_sha256` from inspect (null only for a new file), and either `edits:[{"old":"exact unique text","new":"replacement"}]` plus optional `append`, or `content` for a new/non-daily note. An existing daily file must use targeted edits/append. Use native file tools or apply_patch to prepare the JSON; the controller performs the note mutation.

The controller takes an OS lock, compares current hashes, validates all prepared text, stores private before/after snapshots, performs atomic replacements and verifies each result. It rejects outside-vault paths, hidden files, frozen memory, duplicate keys, invalid dates and edits to old daily sessions. A crash after a partial multi-note commit can resume the same transaction from its prepared bytes. A conflicting concurrent edit is retained and reported; re-read and rebuild the affected operation, never overwrite it.

Snapshots are local under `<BRAIN_BACKUPS_DIR>\<transaction-id>\`. They have no remote and do not create Git commits. Explicit restore uses:

```powershell
python $vaultCtl inspect '<note-path>'
python $vaultCtl restore '<snapshot-id>' '<note-path>' --expected-sha256 '<current-hash>'
```

Restore verifies the old snapshot, checks the current hash, and snapshots the current version before restoring exact prior bytes. It does not delete newly created notes or touch frozen memory. Confirm the intended note/version before a restore.

## Daily checkpoints and coverage

Use [[Daily Note Template]] for model-created daily notes. Location: `01 - Daily Notes/<MM - Month YYYY>/<YYYY-MM-DD>.md`. Event-local dates/times choose the filename, date heading and session timestamp; the actual write date stamps frontmatter. Split multi-day transcripts by event day. Backfills do not replace a later event's Open line.

The body starts with `# Saturday, September 5, 2026`, then `**Open for tomorrow:**`, then `## Index`. Insert one bold-topic, past-tense outcome bullet per new session. Append `## Session N — 3:42 PM: Topic — model-signature`; choose max+1 at write time, never renumber existing labels. All five `###` sections appear in this order: What Got Done; What's Still In Progress; Decisions Made; Notes Touched; Profile Updates. Use `- None` for an empty section.

Existing session bytes and Index entries are immutable. The three permitted body operations are Index insertion, appending a complete session, and updating Open for tomorrow. Restamping frontmatter is an explicit metadata exception. Corrections/gaps always get a new section with provenance. Never fill an old session or rewrite the daily file wholesale. Historical headers before the Open-line convention began on September 3, 2026 remain unchanged; enforce that field for newer notes.

For a live checkpoint:

```powershell
python $vaultCtl checkpoint-context --source codex --session '<actual-id>' --transcript '<actual-jsonl-path>'
python $vaultCtl checkpoint --source codex --session '<actual-id>' --transcript '<actual-jsonl-path>' --input '<checkpoint-json>'
```

Use `--source claude` for Claude. Context returns the verified model and source-local event day/time. Input fields:

```json
{
  "reason": "Recorded verified implementation and remaining acceptance.",
  "days": [{
    "day": "<event-day>",
    "time": "<event-local-time>",
    "topic": "Concrete topic",
    "sections": {
      "What Got Done": ["Past-tense verified outcome."],
      "What's Still In Progress": ["Remaining next action, or None."],
      "Decisions Made": ["Confirmed decision, or None."],
      "Notes Touched": ["[[Relevant Note]]"],
      "Profile Updates": ["None"]
    },
    "open_next": "One concrete next action."
  }],
  "operations": []
}
```

Operations use the shared writer format. If substantive work is already recorded, use `disposition: already_covered`, no days/operations, and `anchors:[{"path":"<daily path>","text":"<exact complete existing session fragment>"}]`. For a truly trivial turn, use `disposition: trivial`, a substantive reason, and no writes. Context can supply source evidence; the controller verifies it. Do not classify a useful audit, decision or unresolved implementation as trivial merely because no code changed.

Receipt states distinguish requested, captured, already_covered, trivial, deferred and failed. Only a verified daily anchor or a reasoned, evidence-backed trivial disposition advances coverage. Source line hashes, byte ranges and fragment numbers bind each receipt to actual evidence. No mtime, exit code, gate flag or unrelated write can certify completion. Large records are split into fragments; unread fragments remain pending. Hidden model reasoning and binary attachments are excluded from capture evidence.

Live capture remains primary. The idle-window backstop reads Claude's queue and discovers changed Codex sessions from the previous seven days after five minutes without transcript changes. It consumes uncovered fragments incrementally and preserves failed work. It never resumes a conversation, closes a client, or executes commands from a transcript.

## Related notes and ledgers

Use wikilinks for named businesses/platforms and directly referenced notes; not generic words, duplicate links or self-links. Folders 02–07 have named indexes covering their notes with stable one-line descriptions and author tags. Update indexes for new, renamed, moved or materially changed notes. Scan direct backlinks for drift.

Keep one current-state block per project. Update Active Priorities only when work or its state changes: at most five Active Now items, one touched date per actionable bullet, older-than-14-day items move to Review, no automatic deletion or archiving. Parked/Watch is non-actionable reference.

Append deliberate decisions. Supersession changes only the old row's status/reference; original wording remains. Preserve old dead-end entries; append a dated resolution when a new method replaces their recommendation. Profile changes require directly confirmed evidence, belong only in Who I Am, and are logged under daily Profile Updates. Routine work does not authorize rewriting protected startup preferences/rules.

## Handoffs and manual use

Follow [[Handoff Template]] and the mirrored handoff skill. Keep one current block at the top of the tracking note, with a runnable Resume line, current state, next action, outstanding inputs and linked artifacts. Durable vault location; no secrets; no duplicate history.

Obsidian's Daily Notes command uses `10 - Resources/Templates/Manual Daily Note Template.md`, folder `01 - Daily Notes`, and date format `MM - MMMM YYYY/YYYY-MM-DD`. Templates points at `10 - Resources/Templates`, whose map is [[Templates]]. Manual sections are signed human. An existing day's note opens unchanged. Agent creation continues through the shared controller and canonical model template.

## Maintenance and acceptance

Deterministic hygiene scans all live notes for schema, daily headers, folder membership/signatures, skill parity, shared boot parity, the approved task/hook runtime baseline and priority aging. It repairs unambiguous missing metadata and index/aging mechanics; ambiguous semantic changes require evidence and reconciliation. Hygiene makes no model calls.

Model capture runs with read-only tools, stdin transport, a bounded timeout and structured output. The controller alone commits. All attempts record outcome, actual model, reported input/output/cache usage, reported cost when available, and retry/reset time. Missing usage or cost stays null, not a fabricated zero. Known quota resets suppress later launches until retry time.

Current implementation/test evidence belongs in the pipeline note and today's daily session. Record tested versus user-confirmed status explicitly. An internal hook error fails open and is logged; a scheduled failure leaves work pending. Keep the existing hidden launcher, Interactive task identity, five-minute idle/fullscreen guards and user pause toggle.
