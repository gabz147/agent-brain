---
status: active
project: meta
type: reference
updated_by: human
updated: 2026-10-17
---

# Dead Ends

What was tried, why it failed, and what to do instead. The counterpart of "bank the working method": the winning method lives in the operation's own note, but the failed attempts would otherwise be scattered inside those notes and only surface if you already knew which one to open. Search this file first when something is not working.

## Rules

- **Add a line the moment an approach is abandoned for a working one.** Recurring operations only; not one-off typos.
- Format: `- **operation** — tried: X. Failed: Y. Do instead: Z. → [[source note]] (YYYY-MM-DD, agent)`. One line.
- Group under headings by area; add a heading when nothing fits.
- Look up an operation with `rg -n '^## ' 'Dead Ends.md'`, then read the matching section, or `rg -n -i -m 8 '<term>' 'Dead Ends.md'`.
- Never delete a line. If a dead end stops being one (a tool update fixes it), append `— resolved YYYY-MM-DD: …`.

## Vault maintenance

- **Renaming a note** — tried: shell `mv`. Failed: every `[[link]]` to it breaks. Do instead: rename inside Obsidian (auto-update links), or fix every reference by hand.
