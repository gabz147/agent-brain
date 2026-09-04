---
status: active
project: meta
type: reference
updated_by: human
updated: 2026-01-01
---

# Handoff Template

Reusable format + procedure for when the user says **"hand off"** (or "make a handoff", "hand off for later", "pausing this"). Goal: a fresh session — this AI after a reset, another agent, a different tool — can resume the work cold without re-deriving anything.

## Procedure (what the agent does on "hand off")

1. **Find or create the project's tracking note.** One note per project/task is the single source of truth. If none exists, create it in the right folder with full frontmatter.
2. **Put a `## Handoff — resume here` block at the TOP of that note**, filled from the skeleton below. Top = first thing a resumer sees.
3. **Point, don't duplicate.** The block references the full note's own sections (and any brief/PRD/plan by path). Don't restate the body — link to it.
4. **Sync the map.** Make sure `Active Priorities.md` has the item and today's daily note logs the handoff. A resumer reads those at startup.
5. **Redact secrets.** Never write passwords/keys/card numbers/tokens. Reference where they live.
6. **State the ONE next action** concretely enough to execute without asking.
7. **Write the `Resume:` line as something a fresh session runs first**, not a description: the working directory to start in, the note to read, the skill to load. It removes the first five minutes of every resumed session.
8. Keep it current: on later work, refresh the block's date + state rather than stacking stale copies.

## The block skeleton

```markdown
## Handoff — resume here
_Last updated: YYYY-MM-DD by claude_

**Resume:** `cd <working dir>` · read [[<this note>]]#Handoff · skill `<name or none>` · then: <first command or action>

**State:** <one paragraph — where this stands right now, what's done, what's live.>

**Next action:** <the single concrete first thing to do on resume.>

**Open decisions (need the user):**
- <decision> — options: A) … B) …

**Waiting on the user (inputs needed):**
- <info/credential/confirmation still owed, and when it's needed by.>

**Do NOT:** <irreversible/outward-facing actions to avoid without explicit go — submit payment, send, publish, delete, etc.>

**Key artifacts (read these, don't re-derive):**
- <this note's own sections> · <brief/plan path> · <repo/url> · <related [[notes]]>

**Suggested skills to invoke on resume:** <skill names, or "none">
```

## Notes

- Handoffs are durable and live in the vault, never in an OS temp dir (temp gets wiped; the vault is the memory).
- A handoff is not a status report to the user; it's instructions to the next agent. Write it to be *executed*, not read.
