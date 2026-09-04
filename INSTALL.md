# INSTALL — for the installing agent

You are an AI coding agent (Claude Code, Codex, or similar) setting up the **agent-brain** memory system on this machine for your human. Follow these steps in order. Do not skip verification. Where a step says "confirm with the user," stop and ask — do not guess.

This repo is a **template**. Your job is to lay it down on the real machine, wire it to the agent harness, and fill in the human's specifics. Nothing here is destructive if you follow the merge steps for `settings.json`.

---

## 0. Preconditions — check, then confirm

Run these and report results before doing anything else:

- OS and shell (`node --version`, `python --version`, `git --version`).
- Whether Claude Code is installed and where its config dir is (`~/.claude` on most setups; `%USERPROFILE%\.claude` on Windows).
- Whether Obsidian is installed (not required to run — the vault is plain Markdown — but the human usually wants it).

Then **confirm with the user**:
1. Where the **vault** should live (default: `~/Documents/Brain`). This becomes `BRAIN_VAULT_ROOT`.
2. Whether they want the **optional automation module** (self-populating daily notes + nightly audit). Default: no. If unsure, install the core only; automation can be added later.
3. Their **name/role and working preferences**, to fill the profile in `VAULT-INDEX.md` and `boot/CLAUDE.md`. If they'd rather do it themselves, leave the template placeholders.

---

## 1. Lay down the vault

Create the vault at `BRAIN_VAULT_ROOT` and copy the contents of this repo's `vault/` into it:

```
<BRAIN_VAULT_ROOT>/
  VAULT-INDEX.md
  Active Priorities.md
  Decisions.md                 ← decision ledger (locked / active / superseded rows)
  Dead Ends.md                 ← what failed and what to do instead; search it first
  Automation Costs.md          ← per-run ledger the automation scripts append to (optional module)
  Machine Inventory.md         ← tasks, hooks, ports, versions on this machine (fill in)
  00 - Inbox/
  01 - Daily Notes/Daily Note Template.md
  02 - Example Project/02 - Example Project.md
  09 - Archive/
  10 - Resources/Handoff Template.md
```

- Delete the `.gitkeep` files once real notes exist.
- Rename/duplicate `02 - Example Project` per the human's real projects, and update the **Vault Structure** map and project mapping in `VAULT-INDEX.md` to match.
- Fill in **Who I Am** and **My Preferences** in `VAULT-INDEX.md` from what the user told you (or leave placeholders if they declined).

## 2. Set environment variables

Set these as **user** environment variables so every tool agrees:

- `BRAIN_VAULT_ROOT` = the vault path from step 0.
- `BRAIN_AUTOMATION_DIR` = the automation dir (only if installing automation; default `~/.claude/vault-automation`).

Windows (PowerShell, per-user, persists):
```powershell
setx BRAIN_VAULT_ROOT "C:\Users\<you>\Documents\Brain"
# if using automation:
setx BRAIN_AUTOMATION_DIR "C:\Users\<you>\.claude\vault-automation"
```
macOS/Linux: add `export BRAIN_VAULT_ROOT=...` to `~/.zshrc` / `~/.bashrc`.

> The hooks fall back to `~/Documents/Brain` and `~/.claude/vault-automation` if these are unset, but setting them explicitly is strongly recommended — it is the single source of truth for the vault location.

## 3. Install the boot file

Copy `boot/CLAUDE.md` to where Claude Code auto-loads it:
- Global: `~/.claude/CLAUDE.md`, **or**
- Per working directory: `<your working dir>/CLAUDE.md`.

If one already exists, **merge** — do not clobber. Fill in the identity/welcome-line and the "Make it yours" section from the user's preferences.

If a second agent (e.g. Codex) shares the vault, copy `boot/AGENTS.md` to its config dir (`~/.codex/AGENTS.md`).

## 4. Install the skill

Copy `skills/obsidian-vault/` to `~/.claude/skills/obsidian-vault/`. (For Codex, mirror to `~/.codex/skills/obsidian-vault/`.) This is the retrieval/write procedure the agent invokes for vault work.

## 5. Install the hooks

Copy `hooks/vault/` to `~/.claude/hooks/vault/`:
- `validate-vault-frontmatter.py` — PostToolUse: blocks any vault `.md` write whose frontmatter breaks the five-key schema.
- `stop-vault-gate.js` — Stop: after a substantive turn, wakes the model with a checkpoint instruction (the same "Vault checkpoint due" prompt you may have seen).
- `session-end-enqueue.js` — SessionEnd: only relevant with the automation module; harmless otherwise.

## 6. Wire the hooks into settings.json

Open `~/.claude/settings.json`. **Merge** the three hook blocks from `settings/vault-hooks.snippet.json` into the existing `hooks` object — append to each array (`PostToolUse`, `Stop`, `SessionEnd`); never overwrite the whole file if it already has hooks.

Substitute `{{CLAUDE_DIR}}` with the absolute path to the `.claude` dir (forward slashes, e.g. `C:/Users/you/.claude`). Ensure `node` and `python` resolve on PATH; if not, replace them with absolute exe paths.

Validate the JSON after editing (`python -c "import json,sys;json.load(open(sys.argv[1]))" ~/.claude/settings.json`). A broken settings.json disables the harness.

## 7. Verify the core (do not skip)

1. **Frontmatter hook fires:** in a Claude Code session, write a `.md` file under the vault with a bad frontmatter (e.g. missing `updated`). The write must be blocked with a "Vault frontmatter violation" message. Then write a valid note — it must succeed.
2. **Daily note flow:** create today's daily note from `01 - Daily Notes/Daily Note Template.md`; confirm it passes the hook (`status: active`, `project: personal`, `type: log`).
3. **Stop gate:** do a small substantive task, end the turn, and confirm the "Vault checkpoint due" wake fires (it is asyncRewake, so it appears as a follow-up). If it never fires, check that `node` runs the hook without error: `echo '{}' | node ~/.claude/hooks/vault/stop-vault-gate.js; echo $?` should print `0`.
4. Report exactly what you tested and the result.

## 8. Optional — automation module

Only if the user opted in at step 0. Follow `automation/README.md` end to end: copy the folder, dry-run both scripts, register the two scheduled tasks, tune the presence guard. Verify via `drain.log` / `audit.log`. This is Windows-only.

## 8.5. Optional — Agent Pulse Obsidian plugin

Only if the user wants the in-Obsidian indicator. Copy `plugins/agent-pulse/` to `<BRAIN_VAULT_ROOT>/.obsidian/plugins/agent-pulse/` (all three files: `manifest.json`, `main.js`, `styles.css`). Then, in Obsidian: Settings → Community plugins → turn **Restricted Mode off** → enable **Agent Pulse**.

It's an unsigned local plugin, so it will not appear in the community directory — that's expected. It reads the automation module's runtime files under `BRAIN_AUTOMATION_DIR`; with automation not installed those files are simply absent and the orb stays idle (the refresh button still works). Clicking the orb writes `automation-state.json` in that dir — the pause toggle the automation scripts and the Stop gate honour. Desktop only. See `plugins/agent-pulse/README.md` for details.

## 9. Optional — git + Obsidian

- If the user wants the vault version-controlled, `git init` inside `BRAIN_VAULT_ROOT` and commit. (Keep private notes private — a vault repo should usually be a **private** GitHub repo.)
- Open `BRAIN_VAULT_ROOT` as an Obsidian vault so `[[wikilinks]]` and the graph work, and so renames auto-repair links.

## 10. Finish

Summarize: vault path, which pieces installed (core / automation), what you filled in vs. left as placeholders, and the verification results. Tell the user the one thing they still need to do by hand (usually: fill the profile, or open the vault in Obsidian).
