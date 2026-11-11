---
name: handoff
description: "Create or refresh a durable handoff in the user's shared vault so any agent can resume the work."
---

# Durable handoff

`<BRAIN_VAULT_ROOT>` is the vault your boot rules resolve; it is a placeholder, not a literal path.

Read `<BRAIN_VAULT_ROOT>/10 - Resources/Handoff Template.md`; from `Vault Workflow Contract.md` in that folder load only the Handoffs and manual use section when it is not already in context. Apply the shared obsidian-vault skill for retrieval and writes.

Create or update one `## Handoff — resume here` block at the top of the existing tracking note; keep it to at most 3,000 characters of current state and replace stale state instead of appending. Keep it in the vault, never OS temp. The Resume line gives cwd, note, suggested skill and the first executable action. Reference existing plans, files and decisions by path/link; do not duplicate their contents.

Include current verified state, one next action, necessary user inputs/decisions, constraints, key artifacts and suggested skills. Preserve secrets by referencing their secure storage rather than copying values. Tailor the handoff to any focus the user supplied.

Sign with the verified runtime model (for example `opus 5.5`) and the real local write time; `vaultctl.py stamp --model <runtime model id>` prints both. Preserve historical authorship and commit through the shared writer. Reconcile the project's index and Active Priorities, then append a daily checkpoint with a verified source receipt.
