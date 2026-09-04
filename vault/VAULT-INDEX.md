---
status: active
project: meta
type: index
updated_by: human
updated: 2026-01-01
---
# VAULT INDEX

Read this file at the start of every conversation. It has two jobs: **the profile of the person you work for** (who they are, how they think, how to work with them) and **the map of this vault** (the structure, the indexes, and the rules for maintaining it). Your own identity is not here — that lives in the boot file (`CLAUDE.md`), which survives compaction.

> **This is a template.** Fill in "Who I Am", set your real folders under "Vault Structure", and adjust the project list to match. Everything under **Vault Rules for AI** is the reusable engine — keep it. Replace the example specifics, not the rules.

---

## Vault location

This vault lives at the path in your `BRAIN_VAULT_ROOT` environment variable (e.g. `C:\Users\<you>\Documents\Brain`). If you use Claude Desktop, claude.ai, or any AI other than Claude Code, you have to point it at this path (set it in your MCP / filesystem connector, and tell the AI "my vault is here"). An AI can't read or maintain a vault it can't find.

---

## Who I Am

<!-- Replace this with a short profile: your role, your OS/stack, the projects you run, how you like to work. The AI updates this section over time from directly confirmed evidence (see Living Profile below). -->

_[Fill me in. Example: "Solo developer on Windows 11, working heavily with Claude Code. Runs a home server for automation. Builds web apps and games."]_

## Vault Structure

```
00 - Inbox                    ← Capture everything, sort later
01 - Daily Notes              ← Dated logs of what got done, one file per day
02 - Example Project          ← Rename/duplicate per real project you run
09 - Archive                  ← Completed projects and old notes
10 - Resources                ← Cross-project reference material, templates
```

<!-- This is a minimal starter. Add numbered folders per project or area. Any folder holding substantial content carries a folder index named `<Folder Name>.md`. When you add/rename/remove a folder, update this map in the same pass. -->

Folders that hold substantial content each carry a folder index (`<Folder Name>.md`); `00`, `01`, `09`, `10` typically don't — `01` has only the Daily Note Template.

Root files: `VAULT-INDEX.md` · `Active Priorities.md` · `Decisions.md` · `Dead Ends.md` · `Machine Inventory.md` · `Automation Costs.md` (only with the automation module).

## The two root ledgers

- [[Decisions]] — every deliberate cross-session choice, one row each, with status `locked` / `active` / `superseded`. Before acting on anything that might contradict a prior choice, check it here; the boot-file rule "Locked decisions stay locked" points at this table. When a decision is made in a session, append a row.
- [[Dead Ends]] — approaches that failed and what to do instead, grouped by area. Search it **first** when something is not working. When you abandon an approach for one that works, add a line (recurring operations only).
- Machine facts (tasks, hooks, ports, versions) live in [[Machine Inventory]]; the automation's token burn in [[Automation Costs]].

## What's Active Right Now

All open work lives in one note: [[Active Priorities]]. Tag each item with its project where it isn't obvious. Check it at the start of every conversation; verify an item's real state before acting on it (a listed item may already be done).

## My Preferences for Working with AI

<!-- Replace with your own. Example below. -->
- **Terse and technical.** No filler, no preamble, no flattery. Fragments are fine. Use exact technical terms. Code blocks unchanged.

---

## How My Memory Works (for the AI)

This vault is your memory. It is external and effectively unlimited. Do not try to hold all of it at once. Hold only what the current task needs, and trust that everything else is one search away. To find something, start at this index, follow the folder indexes and wikilinks, or search. Knowing a note exists is as good as holding it, because you can retrieve it in one step. This is what lets you operate across everything here without drowning.

---

## Vault Rules for AI

These rules apply to any AI that reads or writes to this vault.

### Frontmatter and Wikilinks

Every note MUST have YAML frontmatter. When you create a note, include it. When you edit an existing note that's missing or has incomplete frontmatter, fix it as part of that write. Don't stop to add frontmatter to files you're only reading. Code files are the exception — no frontmatter or wikilinks in code.

Never ask the user what the frontmatter values should be. Infer them.

### Note format

Simple, legible, readable. No random emojis. Checkboxes are real Markdown checkboxes (`- [ ]` / `- [x]`), never emoji stand-ins. **Append before you create:** default to adding to an existing note rather than spinning up a new one — fewer, fuller notes beat many thin ones. Create a new note only when nothing existing is a logical home.

```yaml
---
status: active
project: [project-slug]
type: plan
updated_by: [claude | codex | human]
updated: [YYYY-MM-DD]
---
```

When creating or editing a note, add `wikilinks`:

**Always link:** anyone in Key People · named businesses, products, and platforms · any note this one directly references, extends, or depends on.
**Never link:** generic words just because a note shares the name · the same target twice in one note · the note's own title.

### How to Determine Each Field

**status** — Default `active`. For existing notes infer from content: in progress / has unchecked items → `active`; all done → `completed`; a future "maybe" → `idea`; was active but gone quiet → `parked`; in the Archive folder → `archived`.

**project** — What the note *serves* (folder is the default, but content wins). Use a short kebab-case slug per project/area. Map each folder to a slug, e.g.:
- `02 - Example Project/*` → `example-project`
- `01 - Daily Notes/*` → `personal`
- `09 - Archive/*` → infer from content / original project
- `10 - Resources/*` → `meta`
- `00 - Inbox/*` → infer from content, else `personal`
- Root-level files → `meta`

<!-- The frontmatter validator hook accepts any kebab-case slug by default. To lock the vault to a fixed set of projects, list them in PROJECT_ALLOWLIST inside hooks/vault/validate-vault-frontmatter.py. -->

**type** — What KIND of document it is (not its topic):
- `index` — a folder index / map-of-content note (or this root index)
- `reference` — a static document meant to be looked up later (specs, knowledge bases, templates, voice guides)
- `guide` — step-by-step how-to, runbook, or build instructions
- `plan` — a strategy, phased build, or multi-step project plan (Active Priorities is a plan)
- `log` — a dated session capture or working note (daily notes are logs)

**updated_by** — which agent last wrote the note. See [Agent Signatures](#agent-signatures).

**updated** — the date of that write, `YYYY-MM-DD`. Verify the system date before writing it.

### Valid Field Values

**status:** `active` | `completed` | `parked` | `idea` | `archived`
**project:** any kebab-case slug (or a fixed allow-list if you lock it in the hook)
**type:** `index` | `reference` | `guide` | `plan` | `log`
**updated_by:** `claude` | `codex` | `human`
**updated:** `YYYY-MM-DD`

All five keys are required on every note. One optional key is tolerated: `aliases` (Obsidian's native alias list; keep it where it exists, don't add it). No other key is allowed. A `PostToolUse` hook (`hooks/vault/validate-vault-frontmatter.py`) enforces this for Claude Code sessions and exits 2 on a violation. Agents not covered by that hook must self-check.

### Agent Signatures

More than one AI may write to this vault (e.g. Claude via Claude Code, Codex via the Codex CLI), with room for more. Every entry is signed so any session, or the user, can tell at a glance who produced what.

| Signer | Who |
|---|---|
| `claude` | Claude Code |
| `codex` | Codex CLI |
| `human` | Written by hand by the user |

The signature appears in **four** places:

**1. Note frontmatter** — `updated_by` + `updated`. This records the **last toucher**, not the original author. Set it to yourself on every write, including edits to a note someone else created.

**2. Folder index entries** — trailing code span:

```markdown
- [[Some Note]] — one-line description. `(claude)`
```

**3. Daily note `## Index` lines** — same trailing tag:

```markdown
- **Topic** — one-sentence outcome. `(codex)`
```

**4. Daily note session headings** — trailing tag after the topic:

```markdown
## Session 7 — 8:25 PM: topic — `codex`
```

Rules: sign only what you actually wrote. **Never rewrite another agent's signature to your own.** If you extend a session section another agent wrote, add your own bullets and sign those, or open a new session section. When two agents touch a note on the same day, `updated_by` holds whoever wrote last, while the index and heading tags preserve the per-entry history.

Each agent has its own boot file, outside this vault, pointing here. A new agent gets its own boot file and a row in the table above.

### Folder Indexes (keep them in sync)

Every folder that holds substantial content (5+ notes, or a distinct area) gets an index note named after the folder: `<Folder Name>.md`, frontmatter `type: index`, listing each note in the folder with a one-line description. The index is a contract: when you create, rename, move, or materially change a note, update its folder's index in the same pass. A stale index makes a future session decide from a wrong map.

**When a new folder is created:** create its `<Folder Name>.md` index at the same time, add an entry to the parent folder's index if it has one, and update the **Vault Structure** map in this file in the same pass. A folder the map doesn't show is a folder no future session will look in.

### Renaming and moving notes

- **Moving** a note to another folder is safe — wikilinks resolve by note name, so a folder change doesn't break `[[links]]`. Update both folders' indexes in the same pass.
- **Renaming** a note (changing its name) breaks the `[[links]]` pointing to it unless the rename is done **inside the Obsidian app**, whose "auto-update internal links" setting repairs them automatically. A shell `mv`, or any rename outside the app, does not. So do renames in the app; if the AI must rename a file directly, it then has to find and fix every `[[old name]]` reference by hand.

### Checkpoint Persistence

Whenever something changes that a future session would need to know, persist it without being asked: update the relevant note, today's daily note, and (only for a new always-on rule) `CLAUDE.md`. Then scan the touched folder's index and any cross-referenced notes for drift and fix it in the same pass. The vault is the memory — keeping it current is not busywork, it's maintaining the system itself.

### Archiving

When the user says something is done or asks to archive a note: (1) set its frontmatter `status: archived` and save; (2) move it to the Archive folder, same filename; (3) confirm what was archived and where. Always confirm before archiving. Never archive on your own initiative.

### Writing Rules

Rules the AI always follows when it writes for the user. One worth keeping for everyone: **no em-dashes in marketing or published copy you draft** (sales pages, emails, posts) — em-dashes are a strong "an AI wrote this" tell. Hyphens in normal compound words ("30-day," "well-known") are fine.

- Terse and technical, no filler, no preamble, no flattery. Fragments are fine. Exact technical terms. Code blocks unchanged.

### Daily Notes

Daily notes capture what happened across all of the user's work sessions for a day. They live in `01 - Daily Notes/`, ideally sorted into month subfolders (`01 - Daily Notes/06 - June 2026/`) once the folder fills up. Filename `YYYY-MM-DD.md`. Frontmatter `status: active`, `project: personal`, `type: log`.

Start the body with a human-readable date heading (`# Monday, June 8, 2026`). Right under it sits the note's **one mutable line**, `**Open for tomorrow:** …` — whichever session ends last rewrites it in place (Edit the line, keep the label) with the single thing the next session should pick up first. Then an **`## Index`** block: one bold-topic line per session/entry with a one-sentence outcome. The index makes a day with many entries scannable instead of a wall of prose. Then the entry body follows the Daily Note Template — during setup it is copied into the vault as `01 - Daily Notes/Daily Note Template.md`. Its sections: **What Got Done · What's Still In Progress · Decisions Made · Notes Touched · Profile Updates**. Create every daily note FROM the template; never hand-roll one.

If today's note already exists from an earlier session, append a new session section (`## Session 2`, `## Evening Session`) and add a line to the Index block — don't overwrite. Timestamp each entry with local time. **Session N is a label, not a sequence:** take max+1 when you write, but a collision or out-of-order N (two agents writing at once, a drainer backfilling) is not an error and is never renumbered — the time in the heading is the order, so every heading carries one. Exactly three edits are allowed on an existing daily note: insert an Index bullet, append a session section, rewrite the `Open for tomorrow` line.

#### Trigger 1: Wrap-Up Signal
Never ask the user if they're done working. When they signal it ("I'm done," "calling it," "goodnight"), offer to create or update today's daily note. Always check the actual current date and time first — conversations can stay open overnight.

#### Trigger 2: Review Yesterday's Note at Start of Conversation
At the start of every conversation, after reading this index, check yesterday's daily note (or the most recent weekday if today is Monday).
- **If it doesn't exist:** create it from whatever context you have (chat history, session context), and say it's reconstructed and may be incomplete. Zero context for that day → assume a day off and skip it. Don't create empty daily notes.
- **If it exists:** read its `Open for tomorrow` line first — that is what the last session wanted picked up — then the rest; if you have context it's missing, append a session section; otherwise leave it alone.

This is universal — every AI that reads this vault does it. When multiple AIs work across multiple sessions, no single one sees everything, so each contributes what it knows and the daily note fills in over time. Don't make a production of it. Briefly say what you did and move on.

### Living Profile

This file is a living document. Update the profile sections as you learn new things about the user through conversation. Updates happen silently and are logged in the daily note under "Profile Updates."

**You can update:** Who I Am (only with directly confirmed evidence).
**You must NOT update:** What's Active Right Now (lives in Active Priorities) · My Preferences for Working with AI · Vault Rules for AI.
**Vault Structure is a special case:** never rewrite it on your own initiative, but when a folder is actually created, renamed, or removed, updating the map is part of that change — do it in the same pass.

Judgment: a passing mention is not a personality trait. Check for duplicates/contradictions; if new info contradicts an entry, update that entry rather than adding a second. Match existing tone. Never remove an entry unless explicitly contradicted. Fewer, higher-quality updates.

Log every profile update in the daily note's "Profile Updates" section (e.g. "**Who I Am:** added X").
