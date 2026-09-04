# Agent Pulse — Obsidian plugin (optional)

A tiny, zero-dependency Obsidian plugin that adds two things to the left sidebar's tab strip (right of the **Bookmarks** tab), so you can *see* when a background agent is working in the vault and pick up its edits without restarting Obsidian.

This is optional and self-contained. The rest of agent-brain works without it.

## What it adds

1. **Status orb** — an 8-dot ring that reflects whether a background coding agent has recently touched the vault:
   - `idle` — nothing running (slow, dim).
   - `agent-present` — `claude.exe` / `codex.exe` is alive but not writing (gentle pulse).
   - `active` — actively writing right now: a vault `.md` write in the last 45s, a fresh automation signal, or the drain lock held (faster, brighter, accent-colored).
   - `paused` — you switched the automation off (static, faint, slashed). `active` still wins while something is writing.

   The tooltip names the state, the signal that fired, the file touched, and how long ago; a second line shows how many sessions are queued, the age of the oldest, when the last successful drain ran, and the toggle state — plus a warning once the oldest queued transcript is 20 days old (Claude Code deletes transcripts at 30). Colors come from Obsidian theme variables, so light/dark follow automatically, and all motion respects `prefers-reduced-motion`.

2. **Automation toggle** — clicking the orb cycles **on → AFK paused → ALL paused → on**, writing `automation-state.json` in the automation dir. The scheduled drainer and nightly audit skip while `afk` or `all` is set; the Stop-hook checkpoint also stays silent under `all`. Nothing is lost while paused — sessions keep queueing and drain when you resume. Three command-palette commands do the same without the click: *Toggle AFK automation*, *Toggle ALL vault automation*, *Resume vault automation*.

3. **Refresh button** — a soft refresh that reloads the open Markdown panes **in place** so external agent edits appear, with a brief fade and one spin of the icon. It deliberately does **not** run Obsidian's full `app:reload` (which tears the whole window down and rebuilds it — a visible collapse/respring). Motion is opacity/transform only, so it's compositor-driven and rides your monitor's refresh rate automatically.

## Signals it reads

The orb watches the optional automation module's runtime files under `BRAIN_AUTOMATION_DIR` (falls back to `~/.claude/vault-automation`): `stop-state.json`, `queue.jsonl` / `queue.batch.jsonl`, `.drain.lock`, `automation-state.json`, and the tail of `drain.log` (for the last successful drain), plus a `tasklist` process check and Obsidian's own vault-write events. If you don't run the automation module, those files simply won't exist — every poll treats a missing file as "no signal", so the orb just stays idle and the refresh button still works.

No configuration is required beyond the `BRAIN_AUTOMATION_DIR` env var that the rest of agent-brain already uses.

## Install

Copy this folder to your vault's plugins dir:

```
<BRAIN_VAULT_ROOT>/.obsidian/plugins/agent-pulse/
  manifest.json
  main.js
  styles.css
```

Then enable it: Obsidian → Settings → Community plugins → turn **Restricted Mode off** → enable **Agent Pulse**. (It's an unsigned local plugin, so it won't appear in the community directory — that's expected.)

Desktop only: it uses Node's `fs` / `child_process`, available under Electron.

## Notes

- No build step, no npm dependencies — hand-written CommonJS.
- If the Bookmarks tab header isn't present (sidebar collapsed, Bookmarks core plugin off, or an Obsidian build with no Bookmarks tab), the two icons fall back to the left ribbon automatically.
