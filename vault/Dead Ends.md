---
status: active
project: meta
type: reference
updated_by: human
updated: 2026-01-01
---

# Dead Ends

What was tried, why it failed, and what to do instead. The counterpart of "bank the working method": the winning method lives in the operation's own note, but the failed attempts would otherwise be scattered inside those notes and only surface if you already knew which one to open. Search this file first when something is not working.

## Rules

- **Add a line the moment an approach is abandoned for a working one.** Recurring operations only; not one-off typos.
- Format: `- **operation** — tried: X. Failed: Y. Do instead: Z. → [[source note]] (YYYY-MM-DD, agent)`. One line.
- Group under headings by area; add a heading when nothing fits.
- Never delete a line. If a dead end stops being one (a tool update fixes it), append `— resolved YYYY-MM-DD: …`.

## Vault automation (Windows)

These shipped with the template because they cost the original author real debugging time.

- **Headless `claude -p` from a scheduled task** — tried: launching with the task's default working directory. Failed: cwd is `C:\WINDOWS\system32`; the sandbox denies every path under the user profile, and the child exits 0 after saying so. Do instead: `-WorkingDirectory` on the vault plus `--add-dir` for the transcript tree (the shipped scripts do this). → `automation/README.md`
- **Trusting exit 0 from a headless child** — tried: journaling any exit 0 as processed. Failed: sandbox-blocked and rate-limited runs both exit 0. Do instead: verify a named vault file changed, or accept only a whitelisted no-op line. → `automation/drain-queue.ps1`
- **Transcript byte size as a triviality signal** — tried: "under 64 KB is trivial". Failed: an 86 KB transcript held one prompt and a 344-char reply. Do instead: count `tool_use` blocks and assistant text chars. → `automation/drain-queue.ps1`
- **`Start-Process -PassThru` exit codes (PowerShell 5.1)** — tried: reading `$p.ExitCode` after `WaitForExit`. Failed: stays `$null` unless the handle is cached. Do instead: `$null = $p.Handle` right after `Start-Process`.
- **Hidden scheduled PowerShell** — tried: `powershell.exe -WindowStyle Hidden`. Failed: conhost still flashes and steals focus, tabbing fullscreen games out. Do instead: `wscript.exe run-hidden.vbs` with window style 0.
- **Idle detection from a service task** — tried: S4U / session-0 logon type. Failed: `GetLastInputInfo` only sees its own session, so it always reads "away". Do instead: keep `LogonType=Interactive`.
- **`ConvertTo-Json` on `Get-Content` strings** — tried: serialising the raw lines. Failed: ETS members (`PSPath` etc.) make `-Depth 10` walk the provider graph and hang. Do instead: cast to `[string]` first.
- **Leaving a drain backlog for the scheduled run** — tried: waiting for an idle window. Failed: Claude Code deletes transcripts after 30 days; sessions were lost. Do instead: drain any backlog before day 30 (the drainer and the Agent Pulse tooltip warn at 20 days).

## Obsidian / Electron

- **Screenshotting Obsidian** — tried: `PrintWindow`. Failed: returns stale Electron frames. Do instead: CDP `Page.captureScreenshot` (launch with `--remote-debugging-port`; 9222 is usually Chrome's, pick another).
- **Finding the Bookmarks tab** — tried: anchoring on `aria-label`. Failed: it is the localized display string. Do instead: `data-type="bookmarks"`.
- **Vault write events** — tried: `vault.on('create')` at plugin load. Failed: replays every file at startup. Do instead: register inside `onLayoutReady` plus a warm-up guard.
- **Repositioning ribbon icons** — tried: a plain `MutationObserver`. Failed: self-triggers on its own DOM writes. Do instead: `takeRecords()` in `finally` plus an idempotency check before every write.
- **Detecting agent activity from log mtimes** — tried: watching `drain.log` / `audit.log`. Failed: they are written on every hourly deferral. Do instead: `queue.jsonl`, `stop-state.json`, `.drain.lock`.
- **Renaming a note** — tried: shell `mv`. Failed: every `[[link]]` to it breaks. Do instead: rename inside Obsidian (auto-update links), or fix every reference by hand.
