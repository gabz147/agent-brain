---
status: active
project: meta
type: log
updated_by: human
updated: 2026-01-01
---

# Automation Costs

One row per headless Claude run the optional automation module makes (drainer child per session, nightly audit per day), so the token burn is measurable instead of guessed. `drain-queue.ps1` and `nightly-audit.ps1` append the rows themselves (`Add-AutomationCostRow` in `user-busy.ps1`) and restamp the frontmatter. Set `BRAIN_COST_LEDGER` to move this note; by default the scripts look for it under a `04 - Agent Orchestration & Tooling/` folder first, then at the vault root.

Read this before changing the drain cadence: two weeks of rows say whether hourly draining earns its cost or whether a slower schedule captures the same sessions.

## Columns

`date` local run date · `run` `drain` or `audit` · `session` first 8 chars of the session id (audit: the date range) · `transcript KB` · `duration s` child wall time · `outcome` `verified` / `verified-weak` / `no-op` / `unverified` / `rate-limited` / `blocked` / `timeout` / `error` (audit: `success` / `unverified` / `failure`) · `wrote` notes named by the child · `notes`

## Totals

Update monthly: runs, verified captures, no-ops, failures, and minutes of child time (sum of `duration s` / 60).

## Ledger

The scripts append to the end of this file, so this table must stay the last section of the note.

| date | run | session | transcript KB | duration s | outcome | wrote | notes |
|---|---|---|---|---|---|---|---|
