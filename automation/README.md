# Shared controller

The Python controller is required for live vault writes and checkpoints. Nothing in this package starts a model call on its own: checkpoints are written live by the agent inside its own session.

## Components

| Files | Purpose |
|---|---|
| `vaultctl.py`, `vault_core.py`, `vault-schema.json` | Shared CLI, schema, containment, locks, snapshots, atomic commits, and exact-byte restore |
| `vault_sources.py` | Claude/Codex transcript fragments, real model attribution, and source-bound coverage |
| `vault_capture.py` | Validates checkpoint proposals and records source-bound receipts; controller alone writes |
| `vault_hooks.py` | Live Stop decision logic; a request never claims capture |
| `vault_gate.py` | Transcript-free hook logic for any agent with a hooks manifest (Codex today): session baseline, post-tool validation and turn log, a Stop gate on logged writes, git and controller-commit deltas, emitted in the agent's dialect; fails open |
| `vault_recall.py` | Read-only session brief, recall eval, consolidation digest and `(as of <date>)` fact freshness; no index |
| `obsidian_read.py` | Optional read-only Obsidian CLI observations (links, backlinks, properties, local recovery history, write preflight); never writes |
| `vault_adapters.py`, `adapters/*.json`, `BRAIN.md` | One data-only manifest per agent (instructions path and strategy, skills dirs, hooks, transcript adapter), validated against `adapters/schema.json`, plus the shared boot block each agent's file is rendered from |
| `vault_hygiene.py` | Deterministic schema/index/priority checks and boot/skill parity against one rendering per installed agent; runtime drift checks when the optional `contrib/windows-audit` baseline is installed |
| `vault_links.py` | `vaultctl.py links`: read-only wikilink audit (missing targets, ambiguous names, unmatched headings and blocks, orphan candidates) |
| `tests/` | Temporary-vault regression tests; no paid model calls |

## Live commands

Run with the configured environment, or provide `--vault`, `--state`, and `--backups` **before** the subcommand for an isolated fixture.

```powershell
python vaultctl.py inspect '02 - Example Project/Example.md'
python vaultctl.py commit --model '<verified-runtime-id>' --reason '<actual change>' --input '<operations.json>'
python vaultctl.py checkpoint --summary --source codex --session '<id>' --transcript '<actual.jsonl>' --input '<checkpoint.json>'
python vaultctl.py checkpoint --summary --source codex --session '<id>' --transcript '<actual.jsonl>' --trivial '<reason>'
python vaultctl.py checkpoint --summary --source <agent> --model '<verified-runtime-id>' --topic '<topic>' --done '<outcome>' --next '<remaining>' --open '<next action>'
python vaultctl.py validate
python vaultctl.py hygiene
python vaultctl.py recall-eval [--record]
python vaultctl.py consolidate-context [--days 7] [--mark YYYY-MM-DD]
python vaultctl.py fact-freshness [--max-age-days 90]
python vaultctl.py session-brief
```

Use `--source claude` for Claude sessions. The flag form is for any agent without a transcript; its receipt is marked `attested`. See the vault's `Vault Workflow Contract.md` for JSON formats and restore. A concurrent hash mismatch requires fresh reads and a rebuilt operation; never overwrite the other writer's edit. Existing daily sessions are immutable.

## Checkpoints

Capture is live only. The agent writes each checkpoint in its own session through `checkpoint`; there is no background, scheduled or retrospective model capture. The earlier hourly drain (`VaultQueueDrain`, `drain-queue.ps1`, `vault_queue.py` and the SessionEnd enqueue hook) was removed because it spent the user's plan usage on unattended model runs while they were away. A session that ends without a checkpoint is not summarized automatically; checkpoint it later from its transcript if needed.

`already_covered` needs a matching complete daily section; `trivial` needs source evidence and an honest reason. Exit 0, note names, timestamps, unrelated edits, and prose claims cannot certify success.

Upgrading from a release with the drain: the installer removes the retired SessionEnd hook entry. Remove an existing `VaultQueueDrain` task yourself (`Unregister-ScheduledTask -TaskName VaultQueueDrain`); left in place it can no longer start a model and only logs an error. Leftover queue/spool files can be deleted.

## Private runtime files

Keep `state-v2/`, any legacy queue/spool files and journals, logs, toggles, lock files, and snapshots out of public source control. The repository ignores the default in-checkout state locations. Custom directories must also be private.

`automation-state.json` with `paused: true` and scope `afk` pauses the scheduled audit; scope `all` also silences live Stop requests. Agent Pulse controls this toggle. Missing means unpaused; unreadable existing state defers scheduled work. It never discards data.

## Optional extras

The scheduled Windows audit and its runtime baseline, the Obsidian debug-port link checker and the Agent Pulse plugin live in the repository's `contrib/` folder; setup does not install them. For a cross-platform nightly `hygiene --fix`, see `docs/scheduling.md`.

## Readable note timestamps

New writes use `September 23, 2026 at 6:20:14 AM (UTC-06:00)`. Legacy ISO timestamps and date-only notes stay valid. To reformat existing ISO metadata, preview with `python vaultctl.py format-times`, then apply with `python vaultctl.py format-times --apply`. Use `python3` on macOS/Linux. This changes only the `updated` representation: original times, offsets, authors and all note bodies remain unchanged. Hash checks, private snapshots and daily-history protection still apply. It skips date-only notes and frozen archives. Operational JSON receipts keep ISO timestamps for machine use.
