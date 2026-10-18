---
status: active
project: meta
type: guide
updated_by: human
updated: October 18, 2026 at 12:22:29.919962 PM (UTC-06:00)
---

# Vault Workflow Contract

The shared write and checkpoint mechanics for every agent, whatever its client. [[VAULT-INDEX]] holds the profile and map, [[Active Priorities]] open work, [[Decisions]] deliberate choices, [[Dead Ends]] failed recurring approaches; [[Vault Autonomy Pipeline]] records implementation. The boot block keeps the critical rules; this note is read on demand, one section at a time (`vaultctl.py help write <section>` prints one). This template grants no blanket approval: installs and later source changes follow the user's actual authorization.

## Authorship

Sign with the model that actually wrote the entry: a verified runtime ID or its canonical lowercase label (`claude-opus-5-5` signs `opus 5.5`), `unknown-model` with the uncertainty stated, `automation` for deterministic maintenance, `human` for manual writing. Take the model from trusted runtime metadata: a hook payload, the transcript (`message.model`, `turn_context.model`) or a child's reported usage. A configured default is a launch preference, not evidence. Client names (`claude`, `codex`) are not new signatures; they stay valid in history. `model_labels` in `vault-schema.json` may map IDs to labels.

Attribution lives in frontmatter `updated_by`, index and Index bullets ending `` `(model)` ``, and session headings ending `` `model` ``. Preserve historical tags; sign only text you replace; a missing historical tag becomes `unknown-model`, never a guess.

## Schema

`<BRAIN_AUTOMATION_DIR>/vault-schema.json` is the machine definition; `vaultctl.py validate` and hygiene enforce it.

<!-- VAULT SCHEMA START -->
- Required keys: `status`, `project`, `type`, `updated_by`, `updated`.
- Optional existing key: `aliases`. No other keys.
- Status: `active`, `completed`, `parked`, `idea`, `archived`.
- Project: any kebab-case slug; optional project_allowlist in vault-schema.json. Starter values: `example-project`, `personal`, `meta`.
- Type: `index`, `reference`, `guide`, `plan`, `log`.
- Signature: lowercase model label/ID, `human`, `automation`, or `unknown-model`; legacy tags remain valid in history.
- Updated: readable local write time, for example `September 23, 2026 at 6:20:14 AM (UTC-06:00)`; legacy ISO timestamps and `YYYY-MM-DD` dates remain valid. The writer uses the system clock and timezone.
<!-- VAULT SCHEMA END -->

Infer values from evidence; content beats folder defaults (starter: 02 example-project, 01 personal, root and 10 meta; set `folder_projects` for real folders). Inbox defaults to personal; archive keeps its project. Status: active for ongoing, completed only when finished, idea for proposals, parked for deliberate quiet, archived only after authorized archiving. Type: index maps notes, reference stores lookups, guide gives a procedure, plan tracks work, log records events; dated daily notes are `active/personal/log`. Code and frozen `09 - Archive/Old Memory/` are exempt; the frozen folder is read-only. Only [[Manual Daily Note Template]] keeps `updated_by: human` and the literal `updated: "{{date:YYYY-MM-DD}}"`.

## Read and reconcile

Load only what an operation needs: a daily-only or trivial checkpoint, Daily checkpoints and coverage; a topic or ledger write, this section, Shared writer and Related notes and ledgers (plus Authorship or Schema for new notes and signatures); a handoff, Handoffs and manual use with [[Handoff Template]]; maintenance, Maintenance and acceptance. Reuse sections already in context; read the whole contract only to audit or change the workflow.

Read the full target note, its index and directly relevant links right before writing. For a daily append, `vaultctl.py daily-context <daily-path>` gives the Open line and session headings; read the relevant sessions in full. Read a whole daily note only for a full-day review or unclear coverage, and never call an excerpt a full review. A ledger append reads the Rules section plus matching rows. Current claims need source evidence; chronology is not proof. Keep dated disagreements until evidence settles them. Prefer an existing note over a new one.

## Shared writer

Paths resolve from `BRAIN_*` variables, else `~/.agent-brain/config.json`: the vault defaults to `~/Documents/Brain`, the controller (`BRAIN_AUTOMATION_DIR`) to `~/.agent-brain/automation` (older installs `~/.claude/vault-automation`), snapshots to a sibling `<vault name> Backups/versions`. Every agent runs the same commands, as `python <BRAIN_AUTOMATION_DIR>/vaultctl.py <command>` or `brain <command>`: `inspect <note>`, `inspect --hash <note>`, `commit --model <id> --reason <change> --input <json>`, `validate`, `restore <snapshot> <note> --expected-sha256 <current>`.

A commit input is `{"operations":[...]}`. Each operation has a vault-relative `path`, `expected_sha256` (null only for a new file) and either `edits:[{"old":"exact unique text","new":"replacement"}]` with optional `append`, or `content` for a new or non-daily note; an existing daily note takes only edits and append. Hash first (`inspect --hash`), then read, so a write in between fails as a conflict. Prepare the JSON with your own file tools; only the controller mutates notes.

The controller locks, compares hashes, validates, snapshots, replaces atomically and verifies each write. It refuses outside-vault paths, hidden files, frozen memory, duplicate keys, bad dates and edits to old daily sessions, and resumes an interrupted transaction from its prepared bytes. On a conflict, re-read and rebuild; never overwrite. Snapshots stay local (no remote, no Git). Restore checks the current hash, snapshots it, then restores exact prior bytes; it never deletes new notes. Confirm the note and version first. The writer stamps `updated` with the real local write time, also for backfills; never invent historical times or restamp untouched notes.

## Daily checkpoints and coverage

Model-written daily notes use [[Daily Note Template]] at `01 - Daily Notes/<MM - Month YYYY>/<YYYY-MM-DD>.md`. Event-local dates and times pick the file, heading and session time; frontmatter gets the real write time. Split multi-day work by event day; a backfill never replaces a later Open line.

The body is `# Saturday, September 5, 2026`, `**Open for tomorrow:**`, `## Index`, then sessions `## Session N — 3:42 PM: Topic — model-signature` (N is max+1 at write time) with five `###` sections in order: What Got Done; What's Still In Progress; Decisions Made; Notes Touched; Profile Updates (`- None` when empty). Existing sessions and Index entries are immutable; the only body changes are appending a session, inserting an Index bullet and updating the Open line. Corrections get a new session with provenance. Headers older than September 3, 2026 stay as they are.

A checkpoint is one `checkpoint --summary` call. With a transcript (Claude, Codex): `--source claude|codex --session <id> --transcript <path>`, which binds the receipt to transcript bytes and the model. Without one, any agent: `--source <agent> --session <id> --model <runtime id>`, an `attested` receipt with `model_source: self-report`. Both take summary flags: `--topic`, repeatable `--done`, `--next`, `--decision`, `--touched`, `--profile`, plus `--open` to replace the Open line and `--day`/`--time` (`3:42 PM` or `15:42`) when not now. A hook's checkpoint request already names the right flags. Retrying the same flags returns the same receipt and appends nothing. When nothing is durable, `--trivial "<reason>"` replaces the flags; it is refused while the turn holds unsaved writes or durable commands.

JSON on stdin or `--input <file>` (from Windows PowerShell 5.1, use the file) carries what flags cannot: several days (one `days` entry per event day; `checkpoint-context` lists each day's times), note `operations` in the shared writer format, `disposition: already_covered` with `anchors:[{"path","text"}]` quoting an existing complete session, or `disposition: trivial` with a substantive reason. A days entry is `{"day","time","topic","sections":{...},"open_next"}`; the controller fills an omitted day and time. A useful audit, decision or unfinished implementation is never trivial just because no code changed.

The receipt prints identity, signer and daily anchor; full source ranges stay in `state-v2/coverage`. States: requested, captured, already_covered, trivial, failed. Only a verified anchor or an evidence-backed trivial disposition counts. Line hashes, byte ranges and fragments bind transcript receipts to evidence; no mtime, exit code, gate flag or unrelated write certifies completion. Hidden reasoning and binaries are never evidence. Capture is live only: a session that ends without a checkpoint stays uncaptured, and nothing replays a transcript.

## Related notes and ledgers

Wikilink named businesses, platforms and directly referenced notes, not generic words, repeats or self-links. Folders 02–07 have named indexes with stable one-line, signed descriptions; update them for new, renamed, moved or materially changed notes, and check direct backlinks. A new folder needs its index, parent entry and map update together. Rename in Obsidian or repair every incoming link; update both indexes on moves. Never archive unasked. Deliverables stay in project folders; scratch files are intermediates.

Topic notes hold one current-state block and stable reference; history lives in daily sessions or a `<Note> Log`. A task the user repeats gets one Job note from [[Job Template]] in its project folder; it links only the notes that task needs, and each correction becomes a Lessons rule. Index descriptions say what a note covers, never counts, dates or pending items. Each Active Priorities item is one current line (300 characters at most) with state and next action, replaced, never appended: at most five Active Now items, one touched date each, items older than 14 days move to Review, nothing is deleted automatically; Parked/Watch is reference only.

Append decisions; supersession changes only the old row's status and reference. A checkpoint may append rows and change a non-locked row's Enforced in or Status cells; superseding a locked row needs the owner's words and an interactive commit. Keep old dead ends and append a dated resolution when a new method replaces them. Profile changes need directly confirmed evidence, go only in Who I Am, and are logged under Profile Updates. Routine work never rewrites protected startup rules.

## Handoffs and manual use

Follow [[Handoff Template]] and the handoff skill: one current block at the top of the tracking note with a runnable Resume line, state, next action, open inputs and linked artifacts; durable location, no secrets, no duplicated history, at most 3,000 characters.

Obsidian's Daily Notes command uses `10 - Resources/Templates/Manual Daily Note Template.md`, folder `01 - Daily Notes`, format `MM - MMMM YYYY/YYYY-MM-DD`; Templates points at `10 - Resources/Templates` ([[Templates]]). Manual sections are signed human; agents write through the controller and the model template.

## Maintenance and acceptance

Hygiene scans every live note for schema, daily headers, index membership and signatures, boot and skill parity for each installed agent, and priority aging. It repairs only unambiguous metadata, index and aging mechanics; semantic changes need evidence. It makes no model calls, and nothing captures sessions in the background. Dated test evidence goes in the day's session; the pipeline note keeps current state. Record tested versus user-confirmed status. Hook errors fail open and are logged to `hook-errors.jsonl`. Optional tools in the repository's `contrib/` (a scheduled Windows audit, a runtime baseline) document their own guards.

## Read-only Obsidian CLI

Optional (Obsidian 1.12.7+ with its CLI enabled): `obsidian_read.py` offers `diagnostics`, `link-audit`, `backlinks`, `properties`, `history` and `preflight`. It selects the vault by Obsidian's own ID, verifies the native path per request, refuses unsafe paths and bounds each call. It never writes. `preflight` compares hashes around a history read and is not a lock: keep the controller's expected hash. Native links lack freshness and heading checks, and properties include Archive, so `vaultctl.py validate` and `vaultctl.py links` stay authoritative.

## Recall quality and consolidation

All three read Markdown on demand; none adds a database, embedding or index.

- **Recall eval.** [[Recall Eval]] rows are `| question | [[expected note]] | search terms |`. `vaultctl.py recall-eval` checks each expected note ranks top five; `--record` logs misses to `00 - Inbox/Retrieval Misses.md`. Add a row for every real miss; only a persistent miss list justifies proposing an index, and the user approves the design.
- **Consolidation.** `vaultctl.py consolidate-context` (`--since`, `--days`, `--note <Project>`, else since the last mark) lists sessions, touched notes, open items, decisions, dead-end candidates and unresolved links. It is navigation: read the sessions, write topic, priorities and ledger updates through `commit`, checkpoint them, and only then `--mark <through>`. Run it when the user asks.
- **Fact freshness.** Suffix changeable facts with `(as of YYYY-MM-DD)`. `vaultctl.py fact-freshness` reports markers older than 90 days, unparsable markers and an unmarked Machine Inventory. Re-verify before relying on a stale fact; never invent an as-of date.
