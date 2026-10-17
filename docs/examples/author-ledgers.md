# Author ledgers (example)

The original author's Decisions and Dead Ends rows, kept as an example of how the two ledgers fill up over months of real use. They are not installed: the starter vault ships clean ledgers with only the template's own invariants. Several entries refer to components that were removed before v1 shipped publicly, such as the background capture drain.

## Decisions ledger

| Date | Decision | Why | Enforced in | Status |
|---|---|---|---|---|
| (setup) | Markdown is canonical. No database, vector store, or embedding layer unless measured retrieval misses justify it and the user approves the design. | Portability, one source of truth, retrieval works at this size. | `skills/obsidian-vault/SKILL.md` Boundaries | locked |
| (setup) | Boot files (`CLAUDE.md`, `AGENTS.md`) live outside the vault. | They survive compaction and keep the vault pure memory. | boot files | locked |
| (setup) | Every automation component fails open: a bug must never block a real session. | A broken guard that blocks is worse than no guard. | `hooks/vault/` | locked |
| (setup) | Never archive a note on the agent's own initiative. | Archiving is the user's call. | `VAULT-INDEX.md` Archiving | locked |
| (setup) | Double-confirm before any source-code, running-config, commit, push, or deploy change. Vault notes are exempt. | Code is read-only by default. | boot files | superseded by workflow v2 authorization row below |
| (setup) | Existing daily-note session sections are immutable; append only. `Session N` is a label, never renumbered; the heading's time is the order. The `Open for tomorrow` line is the one mutable line. | Bounds any bad append to one extra section; concurrent writers cannot race on N. | `VAULT-INDEX.md` Daily Notes, shared controller | locked |
| (setup) | Automation success means a verified write or an accepted no-op; a headless child's exit 0 is never trusted on its own. | Sandbox-blocked and rate-limited children exit 0. | `automation/nightly-audit.ps1`, shared controller | locked |
| (workflow v2) | Existing in-session authorization persists; ask only for an action not already authorized. Vault checkpoints need no extra confirmation. | Keep the source/config approval boundary without repeated approval loops. | [[Vault Workflow Contract]]; boot files | active |
| (workflow v2) | New work signs the verified runtime model; preserve historical client signatures. | Actual authorship remains distinguishable across clients and retrospective capture. | Shared schema/writer and skills | active |
| (workflow v2) | Daily capture requires verified source receipts; old Index/session bytes remain immutable, with separate frontmatter restamping. | Requests, process exits and unrelated edits do not prove capture. | [[Vault Workflow Contract]]; shared controller | active |
| (workflow v3) | No background or scheduled model capture. Checkpoints are written live by the agent in its own session; nothing starts a model unattended. | An hourly drain spent plan usage on unattended model runs while the user was away. | shared controller; `automation/tests/test_install.py` | active |

## Dead Ends

These shipped with the template because they cost the original author real debugging time.

- **Headless `claude -p` from a scheduled task** — tried: launching with the task's default working directory. Failed: cwd is `C:\WINDOWS\system32`; the sandbox denies every path under the user profile, and the child exits 0 after saying so. Do instead: `-WorkingDirectory` on the vault plus `--add-dir` for the transcript tree (the shipped scripts do this). → `automation/README.md`
- **Trusting exit 0 from a headless child** — tried: journaling any exit 0 as processed. Failed: sandbox-blocked and rate-limited runs both exit 0. Do instead: verify a named vault file changed, or accept only a whitelisted no-op line. → shared controller receipts (the drain that hit this was removed)
- **Transcript byte size as a triviality signal** — tried: "under 64 KB is trivial". Failed: an 86 KB transcript held one prompt and a 344-char reply. Do instead: count `tool_use` blocks and assistant text chars. → historical (the drain was removed)
- **`Start-Process -PassThru` exit codes (PowerShell 5.1)** — tried: reading `$p.ExitCode` after `WaitForExit`. Failed: stays `$null` unless the handle is cached. Do instead: `$null = $p.Handle` right after `Start-Process`.
- **Hidden scheduled PowerShell** — tried: `powershell.exe -WindowStyle Hidden`. Failed: conhost still flashes and steals focus, tabbing fullscreen games out. Do instead: `wscript.exe run-hidden.vbs` with window style 0.
- **Idle detection from a service task** — tried: S4U / session-0 logon type. Failed: `GetLastInputInfo` only sees its own session, so it always reads "away". Do instead: keep `LogonType=Interactive`.
- **`ConvertTo-Json` on `Get-Content` strings** — tried: serialising the raw lines. Failed: ETS members (`PSPath` etc.) make `-Depth 10` walk the provider graph and hang. Do instead: cast to `[string]` first.
- **Leaving a drain backlog for the scheduled run** — tried: waiting for an idle window. Failed: Claude Code deletes transcripts after 30 days; sessions were lost. Do instead: checkpoint live; checkpoint any missed session from its transcript before day 30. — resolved 2026-10-11: the drain is retired; checkpoint live.
- **Unattended background model capture** — tried: an hourly scheduled drain running `claude -p` on idle machines to summarize past sessions. Failed: it spent the user's plan usage on Opus runs while they were away. Do instead: live checkpoints only; the drain, its queue and the SessionEnd enqueue hook were removed.

## Obsidian / Electron

- **Screenshotting Obsidian** — tried: `PrintWindow`. Failed: returns stale Electron frames. Do instead: CDP `Page.captureScreenshot` (launch with `--remote-debugging-port`; 9222 is usually Chrome's, pick another).
- **Finding the Bookmarks tab** — tried: anchoring on `aria-label`. Failed: it is the localized display string. Do instead: `data-type="bookmarks"`.
- **Vault write events** — tried: `vault.on('create')` at plugin load. Failed: replays every file at startup. Do instead: register inside `onLayoutReady` plus a warm-up guard.
- **Repositioning ribbon icons** — tried: a plain `MutationObserver`. Failed: self-triggers on its own DOM writes. Do instead: `takeRecords()` in `finally` plus an idempotency check before every write.
- **Detecting agent activity from log mtimes** — tried: watching `drain.log` / `audit.log`. Failed: they are written on every hourly deferral. Do instead: `queue.jsonl`, `stop-state.json`, `.drain.lock`. — resolved 2026-10-11: queue.jsonl retired with the drain; use stop-state.json and the audit job's .drain.lock.
- **Renaming a note** — tried: shell `mv`. Failed: every `[[link]]` to it breaks. Do instead: rename inside Obsidian (auto-update links), or fix every reference by hand.
