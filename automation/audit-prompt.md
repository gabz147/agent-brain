# Semantic review reference

Scheduled nightly hygiene is deterministic: vaultctl.py hygiene --fix. It does not invoke a language model, so prompt argument parsing, inferred write success and provider quotas cannot prevent schema/index/aging checks.

Use this checklist only during an authorized interactive semantic review:
1. Fully read the selected project notes, their indexes, relevant daily chronology, Active Priorities, Decisions and Dead Ends.
2. Verify current-state claims from primary files/commands. Surface contradictions with dates and source links. Preserve historical daily sections and old decision wording.
3. Keep one current-state/resume block per project and stable scope descriptions in indexes. Reconcile affected priorities using the existing lifecycle; do not auto-archive.
4. Follow 10 - Resources/Vault Workflow Contract.md and the shared writer. New work signs with the actual runtime model. Daily filenames/times use event-local dates; frontmatter uses the actual write date.
5. Checkpoint findings. A review authorizes findings and their checkpoint, not applying source/config fixes without existing authorization.

Retrospective model capture uses capture-prompt.md over stdin in a restricted read-only child; vault_capture.py requires structured source evidence and a verified daily receipt before reporting completion. Both early errors and completed attempts enter state-v2/outcomes.jsonl. Never use substring/mtime heuristics.
