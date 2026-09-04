# Nightly Vault Audit

Vault root: `{{VAULT_ROOT}}`

You are running headless, unattended, as a scheduled nightly audit. Work only inside the vault root above. Be terse and technical in any output you write. No filler. No emojis.

Work through this checklist in order.

## 1. Missing daily notes (date range)

This machine may not be on 24/7, so a scheduled nightly run is routinely missed and catches up later — possibly days later. Do NOT audit only "today". A **Run context** section is appended at the end of this prompt giving the exact date range to cover; it is authoritative.

For **each date in that range**, check for the daily note at `01 - Daily Notes\<NN - Month YYYY>\<YYYY-MM-DD>.md` (e.g. `01 - Daily Notes\07 - July 2026\2026-07-26.md`).

- If it is missing AND there is evidence of work **on that specific date** — notes created or modified that day (`LastWriteTime`), other dated activity in the vault — create it from the template at `01 - Daily Notes\Daily Note Template.md` and fill in what the evidence supports.
- If there is no evidence of work on that date, do nothing for that date. Never create empty daily notes, and never backfill a day just because it falls inside the range.
- Never overwrite or regenerate a daily note that already exists. If one exists but is missing a session that the evidence clearly shows, append a new `## Session N` section — existing sections are immutable.
- The monthly subfolder (`NN - Month YYYY`) may not exist yet for an older date; create it if needed.

## 2. Active Priorities lifecycle

Read `Active Priorities.md` and enforce its age-aware queue mechanically.

- Required section order: `Active Now`, `Next`, `Waiting`, `Review`, `Parked / Watch`. `Active Now` may contain no more than five actionable bullets.
- Every non-sentinel bullet in `Active Now`, `Next`, `Waiting`, and `Review` must end with exactly one inline `` `touched: YYYY-MM-DD` `` marker. `- None` is the only sentinel and needs no marker.
- Compare each `Active Now`, `Next`, and `Waiting` timestamp with the audit run's local date. When more than 14 full calendar days have elapsed, move the complete bullet under the matching project label in `Review`; preserve its timestamp and wording.
- Never age `Review` or `Parked / Watch`. Never auto-delete a review item.
- Remove a struck-through item only when its own text explicitly says it is done; its history already belongs in project and daily notes.
- If a timestamp is missing or malformed, `Active Now` exceeds five items, or placement requires judgment, leave the item where it is and report it through the Inbox audit note.
- If this step changes `Active Priorities.md`, set its `updated_by` to `claude` and `updated` to the audit run's local date.

## 3. Frontmatter schema scan

Every `.md` file in the vault must have YAML frontmatter with exactly these keys, no undeclared keys:

- `status` — one of: `active`, `completed`, `parked`, `idea`, `archived`
- `project` — a kebab-case project slug (matching one of your folders/areas; e.g. `personal`, `meta`)
- `type` — one of: `index`, `reference`, `guide`, `plan`, `log`
- `updated_by` — one of: `claude`, `codex`, `human` (the agent signature)
- `updated` — a `YYYY-MM-DD` date

Daily notes (filename pattern `YYYY-MM-DD.md`) must be exactly `status: active`, `project: personal`, `type: log`.

`aliases` is an allowed **optional** key (Obsidian's native alias list). Never remove it. Skip `09 - Archive/Old Memory/` entirely — it is a frozen pre-migration snapshot in the old format and is exempt from this scan.

Fix violations directly. Infer the correct value from the note's folder location and content — never ask, never leave a violation unfixed if it is mechanically inferable. Remove undeclared/extra keys. Add missing keys with inferred values. Correct invalid enum values.

**Inferring the two signature keys when they are missing:** set `updated` from the file's own last-modified time, and `updated_by` to `claude` unless the note's content clearly shows another agent wrote it. Do **not** overwrite an existing `updated_by` — a note already signed `codex` stays `codex`. Only your own edits to a note make you its new `updated_by`, and since you are the audit, prefer leaving an existing signature intact over claiming it.

## 4. Stale folder indexes

Each folder that holds substantial content carries an index note named `<Folder Name>.md` (matching its own folder name) that lists every note in that folder with a one-line description.

For each such folder: add entries for notes missing from the index, remove entries for notes that no longer exist on disk. Do not remove or rename the index note itself.

Each index entry carries a trailing agent-signature code span, e.g.:

```markdown
- [[Some Note]] — one-line description. `(claude)`
```

For an entry you **add**, sign it from the note's own `updated_by` frontmatter value. For an entry that already exists without a tag, add one derived the same way. Never change a tag that is already correct.

## 5. Vault Structure drift

The `## Vault Structure` section inside `VAULT-INDEX.md` (vault root) must match the real top-level folder layout of the vault. Update it only if a folder was actually added, renamed, or removed since it was last written — do not rewrite it for cosmetic reasons.

## 6a. Machine Inventory drift (report only)

If a note named `Machine Inventory.md` exists anywhere in the vault, read it. Compare its **Agent hooks** table with the `hooks` object in `{{AUTOMATION_DIR}}\..\settings.json` (skip if unreadable) and its **Scheduled tasks** table with the vault tasks that actually exist (if you can run `Get-ScheduledTask`; otherwise say "tasks not checked"). Report any hook, task, or file that exists on one side and not the other to the Inbox audit note. Do not edit the inventory yourself — a human or an interactive session reconciles it.

## 6. Bloat / duplicates (report only, do not merge)

Flag notes that clearly cover the same subject and look like they should be consolidated. Do NOT merge or edit them — this is a judgment call for a human. Just report the candidate pairs/groups and why.

## Output routing

- Items 1–5 are safe, mechanical fixes: apply them directly to the vault files.
- Item 6, and anything else ambiguous or requiring judgment encountered while doing 1–5, gets APPENDED (never overwritten) to:

  `{{VAULT_ROOT}}\00 - Inbox\Audit YYYY-MM-DD.md`

  (substitute today's actual date). Create this file if it does not exist yet, with frontmatter:

  ```yaml
  ---
  status: active
  project: meta
  type: log
  updated_by: claude
  updated: <today, YYYY-MM-DD>
  ---
  ```

  Append a dated section for this run with your findings as a terse bullet list.

## Required final line

Finish with exactly one line of the form `audit complete: <n> notes scanned` (n = the number of `.md` files you actually checked in step 3). The launcher only records a successful audit when it sees this line, so never print it if you could not read the vault.

## Hard constraints

- Never archive a note.
- Never delete a note.
- Never rename a note — renames done outside the Obsidian app break `[[wikilinks]]` that reference it. If a note looks like it should be renamed, report it in the Inbox audit note instead of renaming it.
- Only touch files under `{{VAULT_ROOT}}`.
