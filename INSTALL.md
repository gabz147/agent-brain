# Install and upgrade

Use the user's existing authorization and preferences. Establish the vault location, participating clients, and whether scheduled model capture is wanted before changing the machine. Do not overwrite existing notes, boot files, skills, or settings wholesale.

## 1. Check prerequisites and preserve existing files

Check `python --version`, `node --version`, and the installed agent clients. Python 3.10+ is required; the controller uses only the standard library. Obsidian is optional for agent work. Scheduling requires Windows PowerShell and Task Scheduler; retrospective capture additionally needs a logged-in Claude CLI with the required restricted-mode flags.

For an upgrade, save copies of the installed boot files, skills, hooks, controller/schema, and relevant settings. Preserve pending queues, source receipts, and snapshot directories. Do not copy runtime state into this public repository. The old drainer must not run concurrently while its controller files are replaced; use the existing pause toggle or disable only the two vault tasks during the authorized upgrade, then restore their prior state.

## 2. Copy or merge the starter vault

For a new vault, copy `vault/` to the chosen location, default `~/Documents/Brain`. Fill `VAULT-INDEX.md`'s profile only from the user's confirmed information. Rename the example project and update its index/map as appropriate.

For an existing vault, add or merge the contract and guides under `10 - Resources/`, the model daily template, and the dedicated manual template. Reconcile rules in the existing root index without replacing the user's profile, projects, ledgers, priorities, or daily notes. Preserve historical signatures and all frozen archive bytes.

## 3. Install the shared controller and environment

Copy the source files in `automation/` into `~/.claude/vault-automation`, or a chosen `BRAIN_AUTOMATION_DIR`. The controller is required even if scheduled jobs are disabled. Runtime queues, logs, state, and backups are private and must not be replaced during upgrades.

On Windows, set the chosen paths for this process and future user processes:

```powershell
$env:BRAIN_VAULT_ROOT = Join-Path $env:USERPROFILE 'Documents\Brain'
$env:BRAIN_AUTOMATION_DIR = Join-Path $env:USERPROFILE '.claude\vault-automation'
[Environment]::SetEnvironmentVariable('BRAIN_VAULT_ROOT', $env:BRAIN_VAULT_ROOT, 'User')
[Environment]::SetEnvironmentVariable('BRAIN_AUTOMATION_DIR', $env:BRAIN_AUTOMATION_DIR, 'User')
$vaultCtl = Join-Path $env:BRAIN_AUTOMATION_DIR 'vaultctl.py'
```

Use the confirmed custom paths instead of these defaults when needed. On macOS/Linux, export the same variables in the agent's environment. Existing apps/tasks may need a later restart to see new environment values; do not restart active user work without authorization.

Optional `BRAIN_STATE_DIR` and `BRAIN_BACKUPS_DIR` override private storage. Keep both outside the Markdown vault and any public checkout. Set `BRAIN_PYTHON` if the hook/runner needs an explicit executable. The PostToolUse hook command in the settings snippet must also use the correct interpreter.

Customize `vault-schema.json`'s `folder_projects` for the user's actual folders; an optional `project_allowlist` restricts otherwise valid kebab-case slugs. Keep the shared human schema block synchronized through reviewed hygiene repairs.

## 4. Merge boot rules and install both skills

Merge `boot/CLAUDE.md` into `~/.claude/CLAUDE.md` and, for Codex, `boot/AGENTS.md` into `~/.codex/AGENTS.md`. Boot files stay outside the vault. Their `SHARED VAULT RULES` blocks must be identical.

Copy `skills/obsidian-vault/` and `skills/handoff/` into each participating client's skills directory. Both copies of each `SKILL.md` must be byte-identical. Codex's `agents/openai.yaml` is optional UI metadata. Angle-bracket paths in the skills/contract mean resolved environment paths, not literal folder names.

## 5. Install Claude hook adapters

Copy `hooks/vault/` to `~/.claude/hooks/vault/`. Merge the three arrays in `settings/vault-hooks.snippet.json` into the existing `hooks` object in `~/.claude/settings.json`. Replace `{{CLAUDE_DIR}}` with the absolute directory, using forward slashes and keeping path quotes. Preserve unrelated hooks/settings, then parse the JSON to verify it.

- PostToolUse reports an invalid completed Markdown write with exit 2. It cannot undo the write; the shared controller prevents invalid writes before they happen.
- Stop requests a source-bound checkpoint after substantive work. The request is not evidence that capture happened.
- SessionEnd writes a durable spool record for optional later draining.

Internal hook failures fail open and are logged. Codex does not use these Claude hooks; it checkpoints directly through the shared writer. Optional discovery handles Codex interruptions.

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

## 8. Optional scheduled capture and Agent Pulse

For approved Windows scheduling, follow [automation/README.md](automation/README.md). Its dry runs do not invoke a model or write the vault. Register tasks with hidden launchers, an Interactive user identity, and the five-minute idle/fullscreen/pause guards intact. Record the local runtime baseline only after inspecting the installed task/hook definitions.

For the optional status indicator, install the three runtime files in `plugins/agent-pulse/` into `<vault>/.obsidian/plugins/agent-pulse/`, then enable it in Obsidian. Its activity indicators are not capture receipts.

## 9. Verify and record the result

Report the resolved paths, installed clients/components, automated checks, real smoke-test results, and outstanding acceptance separately. Checkpoint the installation through the shared writer. Keep the real vault private if the user elects to version it; this repository remains the shareable template.
