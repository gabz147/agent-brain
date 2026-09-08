---
status: active
project: meta
type: reference
updated_by: astra
updated: 2026-09-07
---

# Handoff Template

Use when the user asks to hand off or pause work. The handoff is durable instructions for a fresh agent, stored at the top of the existing tracking note. Both handoff skills point directly here. Follow [[Vault Workflow Contract]] for model attribution, shared commits and daily receipts.

## Procedure

1. Read the tracking note and current evidence. Prefer its existing logical home over a new document.
2. Keep one `## Handoff — resume here` block at the top, after frontmatter/title. Replace stale handoff state instead of stacking copies.
3. Point to existing plans, source files, decisions and artifacts; do not duplicate them.
4. Give one runnable Resume line: cwd, note/heading, skill, first action. The next action must be concrete.
5. Include only real open decisions, required inputs and constraints. Never copy secrets; reference secure storage.
6. Reconcile the folder index and [[Active Priorities]], then append a signed daily checkpoint with a verified receipt.
7. Sign with the actual runtime model and actual write date. Event times in daily notes still use the event's local time.

## Skeleton

```markdown
## Handoff — resume here
_Last updated: <actual YYYY-MM-DD> by <verified model>_

**Resume:** `cd <working directory>` · read this note's Handoff section · skill `<name or none>` · then: <first command or action>

**State:** <current verified state; distinguish tested from user-confirmed>

**Next action:** <one concrete action>

**Open decisions:** <only unresolved choices, or None>

**Required inputs:** <only missing information, or None>

**Constraints:** <applicable scope, locked choices, external-action boundaries>

**Key artifacts:** <source sections, project files, plans and related notes by path/link>

**Suggested skills:** <names, or none>
```

Store the handoff in the vault, never OS temp. Keep deliverables in the user's project folders. Daily history stays append-only; this current-state block is intentionally refreshed as work advances.
