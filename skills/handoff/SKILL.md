---
name: handoff
description: "Create or refresh a durable handoff in the user's shared vault so either agent can resume the work."
---

# Durable handoff

Resolve `<BRAIN_VAULT_ROOT>` and `<BRAIN_AUTOMATION_DIR>` from environment variables, defaulting to `~/Documents/Brain` and `~/.claude/vault-automation`. `<HOME>` means the current user home. These are placeholders, not literal paths.

Read `<BRAIN_VAULT_ROOT>\10 - Resources\Handoff Template.md` and `Vault Workflow Contract.md` in that same folder. Apply the shared obsidian-vault skill for retrieval and writes.

Create or update one `## Handoff — resume here` block at the top of the existing tracking note. Keep it in the vault, never OS temp. The Resume line gives cwd, note, suggested skill and the first executable action. Reference existing plans, files and decisions by path/link; do not duplicate their contents.

Include current verified state, one next action, necessary user inputs/decisions, constraints, key artifacts and suggested skills. Preserve secrets by referencing their secure storage rather than copying values. Tailor the handoff to any focus the user supplied.

Sign with the verified runtime model (for example astra or opus 5), preserve historical authorship, and commit through the shared writer. Reconcile the project's index and Active Priorities, then append a daily checkpoint with a verified source receipt.

Both Claude and Codex copies of this skill are byte-identical. Detailed mechanics live only in the vault templates and contract.
