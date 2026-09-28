---
status: active
project: meta
type: guide
updated_by: opus 5.5
updated: September 28, 2026 at 12:09:05 AM (UTC-06:00)
---

# Recall Eval

Known-answer questions that measure whether ordinary vault search finds the right note. `vaultctl.py recall-eval` ranks live notes by filename, headings, wikilinks and body (no index) and checks that the expected note lands in the top five. `--record` appends the result to `00 - Inbox/Retrieval Misses.md`.

Add a row whenever an agent failed to find something that was in the vault: the question as it was asked, the note that held the answer, and the words a searcher would actually type. Replace these starter rows with questions about your own projects. Rules live in [[Vault Workflow Contract]] under Recall quality and consolidation.

| Question | Expected note | Search terms |
|---|---|---|
| What approaches already failed for a recurring operation? | [[Dead Ends]] | dead ends, tried, do instead |
| Which choices are locked and must not be reversed? | [[Decisions]] | decisions, ledger, locked |
| What hardware and scheduled tasks does this machine have? | [[Machine Inventory]] | machine inventory, scheduled tasks, hardware |
| What should I work on next? | [[Active Priorities]] | active priorities, active now |
| How do I write a handoff another agent can resume? | [[Handoff Template]] | handoff template, resume |
| How are daily checkpoints written and verified? | [[Vault Workflow Contract]] | daily checkpoints, checkpoint, receipt |
