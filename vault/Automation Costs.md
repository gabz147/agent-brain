---
status: active
project: meta
type: reference
updated_by: astra
updated: 2026-09-07
---

# Automation Costs

The shared controller records capture outcomes and actual model-reported usage in private `state-v2/outcomes.jsonl`. Run `python "<BRAIN_AUTOMATION_DIR>/vaultctl.py" costs` to summarize it.

Input/output/cache token counts and estimated cost come from the CLI result when provided. Missing values remain unknown; do not turn them into zero. A configured model is not evidence of which model actually ran. CLI cost estimates are not a subscription invoice.

Nightly hygiene makes zero model calls. Capture attempts, timeouts, failures, quota backoff, and deferrals remain distinguishable. Review the actual ledger before changing scheduled cadence.

The previous Markdown row appender and `BRAIN_COST_LEDGER` are retired. Preserve any existing historical rows during an upgrade; new operational totals come from the controller. Store a dated interpretation here only when evidence warrants it.

Related: [[Vault Autonomy Pipeline]], [[Vault Workflow Contract]].
