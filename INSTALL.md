# Install and upgrade

Use the user's existing authorization and preferences. Establish the vault location, participating clients, and whether the optional scheduled audit is wanted before changing the machine. Do not overwrite existing notes, boot files, skills, or settings wholesale.

For guided installation with client selection, start with [LAPTOP-SETUP.md](LAPTOP-SETUP.md). The included `install.py` implements the file-copy and settings-merge steps below. Preview with `python install.py --client <agent>` (an id from `automation/adapters/`, a comma list such as `claude,kiro`, `both` for claude,codex, or `all` detected agents); apply with the same selection and `--apply`. Use `python3` on macOS/Linux. `--wizard` offers the official installer for a missing CLI. Brain paths are merged into selected-client settings automatically; `--persist-env` is a legacy Windows option. Setup does not log in, enable community plugins or register tasks. Use the remaining checks below after installation.

Existing differing workflow files cause an error before writes. After reviewing the differences, `--replace-workflow` backs up replaced files outside the vault, updates package files, and merges the shared boot block while retaining client-specific text. Existing vault notes/templates/app settings, custom schema, queues and receipts remain untouched. Conflicting hook definitions require a manual merge. Backups and their target manifest are under `~/Documents/Brain Install Backups/`. This is a per-file atomic installer, not a multi-file transaction: after an interrupted install, rerun it with the same options.

## 1. Check prerequisites and preserve existing files

Timestamp upgrades preview and migrate the known legacy `Updated` rule in
the existing contract through the shared writer, with a checked hash and private
snapshot. Custom wording is left for review. Other note content and historical
date-only metadata stay intact; new writes receive local time and UTC offset.

To make existing ISO timestamps readable after upgrading, preview
`python <automation-dir>/vaultctl.py format-times`, then add `--apply` to perform
the conversion. This preserves the original time, author and note body, and
creates checked snapshots. Use `python3` on macOS/Linux.

Use `install.py --doctor --client <agents>` to check the chosen agents. Python 3.10+ is required; the controller and the hook adapters use only the standard library. Node.js 22+ is needed only by the optional link checker. Obsidian is optional for agent work. The optional audit task requires Windows PowerShell and Task Scheduler; it never calls a model.

For an upgrade, save copies of the installed boot files, skills, hooks, controller/schema, and relevant settings. Preserve source receipts and snapshot directories. Do not copy runtime state into this public repository. Pause or disable the audit task while its controller files are replaced, then restore its prior state. The Node Stop launcher was replaced by `stop-vault-gate.py` and a SessionStart hook was added: the installer retires the old `stop-vault-gate.js` hook entry on upgrade and leaves that inert file in place. That changes the approved hook wiring, so an existing runtime baseline reports drift until you inspect the new settings and re-record it once with `vaultctl.py snapshot-runtime`. Upgrading only some installed agents is refused before any write when the others hold older copies; rerun with the agent list the error names. The background capture drain was removed: the installer drops the retired SessionEnd hook entry, and an existing `VaultQueueDrain` task should be removed (`Unregister-ScheduledTask -TaskName VaultQueueDrain`), then the runtime baseline re-recorded once.

## 2. Copy or merge the starter vault

For a new vault, copy `vault/` to the chosen location, default `~/Documents/Brain`. Fill `VAULT-INDEX.md`'s profile only from the user's confirmed information. Rename the example project and update its index/map as appropriate.

For an existing vault, add or merge the contract and guides under `10 - Resources/`, the model daily template, and the dedicated manual template. Reconcile rules in the existing root index without replacing the user's profile, projects, ledgers, priorities, or daily notes. Preserve historical signatures and all frozen archive bytes.

## 3. Install the shared controller and environment

Copy the source files in `automation/` (with `automation/adapters/` and `boot/BRAIN.md`) into `~/.agent-brain/automation`, or keep an existing `~/.claude/vault-automation`, or a chosen `BRAIN_AUTOMATION_DIR`; record it as `automation_dir` in `~/.agent-brain/config.json`. The controller is required even if scheduled jobs are disabled. Runtime queues, logs, state, and backups are private and must not be replaced during upgrades.

On Windows, set the chosen paths for this process and future user processes:

```powershell
$env:BRAIN_VAULT_ROOT = Join-Path $env:USERPROFILE 'Documents\Brain'
$env:BRAIN_AUTOMATION_DIR = Join-Path $env:USERPROFILE '.agent-brain\automation'
[Environment]::SetEnvironmentVariable('BRAIN_VAULT_ROOT', $env:BRAIN_VAULT_ROOT, 'User')
[Environment]::SetEnvironmentVariable('BRAIN_AUTOMATION_DIR', $env:BRAIN_AUTOMATION_DIR, 'User')
$vaultCtl = Join-Path $env:BRAIN_AUTOMATION_DIR 'vaultctl.py'
```

Use the confirmed custom paths instead of these defaults when needed. On macOS/Linux, export the same variables in the agent's environment. Existing apps/tasks may need a later restart to see new environment values; do not restart active user work without authorization.

The installer also writes `~/.agent-brain/config.json` with the vault root, controller directory, interpreter and selected clients. The controller and hook adapters read `BRAIN_*` variables first and that file second, so a client that cannot inject environment variables still finds the vault. Optional `BRAIN_STATE_DIR` and `BRAIN_BACKUPS_DIR` override private storage. Keep both outside the Markdown vault and any public checkout. Set `BRAIN_PYTHON` if the scheduled audit runner needs an explicit executable. Every hook `command` in the settings snippet must point at the correct Python interpreter; `install.py` substitutes it for you.

Customize `vault-schema.json`'s `folder_projects` for the user's actual folders; an optional `project_allowlist` restricts otherwise valid kebab-case slugs. Keep the shared human schema block synchronized through reviewed hygiene repairs.

## 4. Merge boot rules and install the three skills

Each agent's instructions file is `boot/BRAIN.md`'s `SHARED VAULT RULES` block plus that agent's one-line tail from `automation/adapters/<id>.json`, merged at the manifest's `instructions.path` (for example `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.kiro/steering/agent-brain.md`). `python install.py --render <id>` prints the exact file for a manual merge. Boot files stay outside the vault; each installed block must equal its rendering.

Copy `skills/obsidian-vault/`, `skills/handoff/` and `skills/source-to-vault/` into one skills directory each agent reads, from its manifest's `skills` list; a shared `~/.agents/skills` serves Codex and Copilot once. Every copy of each `SKILL.md` must be byte-identical. Codex's `agents/openai.yaml` is optional UI metadata. Angle-bracket paths in the skills/contract mean resolved environment paths, not literal folder names.

`source-to-vault` preserves original documents and extracts source packets in project folders outside Brain. Text and DOCX need only Python; PDF extraction additionally uses PyMuPDF. Install that dependency only if needed. Extraction does not replace full source review, OCR, or checking citations against the original.

## 5. Install Claude hook adapters

Copy `hooks/vault/` to `~/.claude/hooks/vault/`. Merge the three arrays (SessionStart, PostToolUse, Stop) in `settings/vault-hooks.snippet.json` into the existing `hooks` object in `~/.claude/settings.json`. Replace `{{CLAUDE_DIR}}` inside each `args` entry with the absolute directory. Set `command` to the actual Python executable. The direct-execution form needs no shell quoting and supports Windows without Git Bash. Claude Code 2.1.270+ is the tested minimum. Preserve unrelated hooks/settings, then parse the JSON to verify it.

- SessionStart prints the session brief into context on startup and resume. It reads notes and never writes.
- PostToolUse reports an invalid completed Markdown write with exit 2. It cannot undo the write; the shared controller prevents invalid writes before they happen.
- Stop requests a source-bound checkpoint after substantive work. The request is not evidence that capture happened.

Internal hook failures fail open and are logged. There is no background capture: a session that ends without a checkpoint is not summarized automatically.

## 5b. Install Codex hook adapters

Copy `hooks/vault/` to `~/.codex/hooks/vault/` and merge the three arrays in `settings/codex-hooks.snippet.json` into `~/.codex/hooks.json`, keeping unrelated hooks. Codex takes a shell command string: replace each `script`/`args` pair with `command` set to the quoted Python executable, the script's absolute path and its two arguments (`codex <Event>`). Codex runs it with `$SHELL -lc` on macOS/Linux and `cmd.exe /C` on Windows, where a path containing `%` or `"` cannot be quoted safely. Hooks are on by default (`[features].hooks`); Codex lists new or changed hooks for review, so open `/hooks` once and trust the three Agent Brain entries.

- SessionStart (startup, resume) prints the session brief, which Codex adds as developer context, and records the session's git baseline.
- PostToolUse on `apply_patch` validates vault notes the patch touched (exit 2 with the problems on stderr) and appends the write to the session's turn log under the private state directory. Shell commands are logged only when `~/.agent-brain/config.json` sets `"hooks": {"shell_log": true}` before setup, which adds `Bash` to the matcher at the cost of one Python start per command.
- Stop runs `vault_gate.py`, which needs no transcript: logged writes, git HEAD/remote/dirty-count changes since the baseline, and controller commits since the session's last receipt each count, and a long answer counts only beside five logged tool calls. It asks at most once per ten minutes and never twice for the same delta, as JSON `{"decision": "block", "reason": ...}`, which Codex turns into a continuation prompt. The request is not evidence of capture.

`vaultctl.py gate --agent <id>` and `vaultctl.py validate --hook <id>` run the same logic from a payload on stdin, in the agent's hook dialect.

## 6. Verify the core in an isolated fixture

Run the regression suite from the checkout:

```powershell
python -m unittest discover -s automation/tests -q
```

It invokes the actual hook adapters with temporary paths, tests invalid/valid metadata, and verifies replay and daily preservation. Do not deliberately put invalid notes into the real vault for a smoke test.

Validate the installed vault:

```powershell
python $vaultCtl validate
python $vaultCtl hygiene
```

Inspect any issues. `hygiene --fix` applies only mechanical repairs but still requires the installation/repair authorization. A schema issue does not authorize rewriting historic daily sessions. For a fixture with no installed boot files, use `hygiene --no-parity`; keep parity enabled for normal installed checks.

Exercise a real live checkpoint using an actual session transcript, first calling `checkpoint-context`. Prepare the five-section summary and hash-checked topic/index changes, then use `checkpoint`. Read back its daily section and receipt. Replaying the identical input must preserve the section rather than append a duplicate. A real CLI checkpoint is a separate acceptance check from the stubbed regression suite.

## 7. Configure manual daily notes in Obsidian

Merge `settings/obsidian-daily-notes.json` into `.obsidian/daily-notes.json` and `settings/obsidian-templates.json` into `.obsidian/templates.json`. Enable the built-in Daily Notes and Templates plugins if wanted. Preserve unrelated Obsidian settings.

Daily Notes should use `01 - Daily Notes`, format `MM - MMMM YYYY/YYYY-MM-DD`, and `10 - Resources/Templates/Manual Daily Note Template.md`. Agent-created notes use the separate model template through the controller.

Test creation in a temporary vault: the date/time tokens expand, the five sections and `human` signatures appear, and repeating the command opens the existing note without changing its bytes. Do not infer real UI acceptance from Python tests.

## 8. Optional scheduled audit and Agent Pulse

For approved Windows scheduling, follow [automation/README.md](automation/README.md). Its dry runs do not invoke a model or write the vault. Register tasks with hidden launchers, an Interactive user identity, and the five-minute idle/fullscreen/pause guards intact. Record the local runtime baseline only after inspecting the installed task/hook definitions.

For the optional status indicator, install the three runtime files in `plugins/agent-pulse/` into `<vault>/.obsidian/plugins/agent-pulse/`, then enable it in Obsidian. Its activity indicators are not capture receipts.

## 9. Verify and record the result

Report the resolved paths, installed clients/components, automated checks, real smoke-test results, and outstanding acceptance separately. Checkpoint the installation through the shared writer. Keep the real vault private if the user elects to version it; this repository remains the shareable template.
