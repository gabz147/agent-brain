# Set up Agent Brain

Agent Brain is a standalone public vault workflow. You need this repository only.
It installs a generic Obsidian vault and three related skills for any agent with
an adapter in `automation/adapters/` (Claude Code, Codex CLI, GitHub Copilot CLI,
Kiro CLI, Qwen Code, Factory Droid), without anyone's personal notes or unrelated skills.

For setup through an agent, open this checkout and ask it to follow
[SKILL.md](../SKILL.md).
The root `agent-brain` skill handles setup; the three skills under `skills/`
handle everyday vault work after installation.

## Prerequisites

- **Obsidian**, already installed: [official download](https://obsidian.md/download).
- **Python 3.10+**, on PATH: [official downloads](https://www.python.org/downloads/).
  On Windows select Add Python to PATH. On Linux use your distribution's Python
  package if it is new enough. Reopen the terminal afterward.
- **Node.js 22+** only if you want the optional link checker in Vault Actions;
  the hooks and the writer need Python alone.
- An account for your chosen CLI. Setup offers a missing CLI's official native
  installer with your approval. Alternatively install
  [Claude Code](https://code.claude.com/docs/en/setup) or
  [Codex](https://github.com/openai/codex#installing-and-running-codex-cli) yourself.

Claude Code **2.1.270+** is the tested minimum for these direct-execution hooks.
They do not require Git Bash. An older installed CLI needs an update before
guided setup can finish.

The bootstrap needs HTTPS access to GitHub and curl on macOS/Linux. Python
downloads one immutable repository revision; Git and GitHub login are unnecessary.
Brain setup requests no administrator permission, permanent execution-policy
change or model call. Vendor installers have their own platform requirements.

## Guided installation

Copy the command for your system from the [README](../README.md#install).

1. Choose your agents by number or id; separate several with commas.
2. Accept the default vault folder (`~/Documents/Brain`) or choose another.
3. Resolve missing prerequisites. If offered, approve the official CLI installer.
   Sign-in happens separately when you start the client.
4. Review the planned files. Differing workflow files require a replacement
   choice and are backed up. Confirm application of the plan.
5. Open the printed folder in Obsidian. Start a fresh CLI session and follow
   [FIRST-CHECKPOINT.md](../FIRST-CHECKPOINT.md). A copy is saved beside the controller.

Startup rules ask agents to checkpoint substantive work, findings, decisions and
handoffs. Claude and Codex also get a startup brief and a Stop-hook reminder. Other agents
run `vaultctl.py session-brief` once and checkpoint with `--source <agent> --model <id>`. Test writing and next-session recall with the guide;
copied files alone do not prove agent behavior.

## Download and inspect

Download the [public ZIP](https://github.com/gabz147/agent-brain/archive/refs/heads/main.zip),
extract it, read `install.py` and this guide, and open a terminal in that folder.
You can also clone this public repo normally with Git.

macOS/Linux:

```bash
python3 install.py --wizard
```

Windows PowerShell:

```powershell
python install.py --wizard
```

For explicit noninteractive setup, preview then apply. Substitute any adapter id,
a comma list such as `codex,kiro`, `both` or `all` for `codex`, and use `python` on Windows:

```bash
python3 install.py --doctor --client codex
python3 install.py --client codex
python3 install.py --client codex --apply
python3 install.py --client codex --verify
```

`--apply` installs and validates workflow files; it does not download a CLI.
Use `--doctor` to check the actual CLI, or the wizard to offer installation.
Provide `--vault "/path/to/Brain"` for a custom vault. Use
`--home "/path/to/test home"` only for an isolated fixture. Native client downloads
are disabled for another home so tests cannot install software into your account.

## Installed locations

| Location | Content |
|---|---|
| Chosen vault | Generic notes, contracts, indexes and Obsidian daily templates/settings |
| Each selected agent's instructions file | Brain startup/writing rules, e.g. `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.copilot/copilot-instructions.md`, `~/.kiro/steering/agent-brain.md`, `~/.qwen/QWEN.md`, `~/.factory/AGENTS.md` |
| One skills folder per selected agent | `obsidian-vault`, `handoff`, `source-to-vault` only; `~/.agents/skills` is shared by Codex and Copilot |
| `~/.agent-brain/automation` | Shared writer/schema, adapter registry, private state and first-checkpoint guide; used by every agent. An existing `~/.claude/vault-automation` install stays where it is |
| `~/.agent-brain/bin` | `brain` (macOS/Linux) and `brain.cmd` (Windows) launchers for controller commands; add to PATH if you like |
| `~/.agent-brain/config.json` | The vault root, controller directory and interpreter, readable by any client or adapter |
| `~/.claude/hooks/vault`, if selected | Claude startup brief, checkpoint reminder and validation adapters |
| `~/.codex/hooks/vault` and `~/.codex/hooks.json`, if selected | The same three hooks for Codex; trust them once in `/hooks` |
| Selected clients' configuration | Hook entries merged with existing settings; Brain variables an earlier release injected are kept current, none are added |

New installs keep the shared controller in `~/.agent-brain/automation`. A home that
already has `~/.claude/vault-automation` keeps using it, because its private state and
receipts live there. Codex-only setup does not install Claude, its boot file, its skills or its hooks.

Brain paths are stored in `~/.agent-brain/config.json`; the controller, hook
adapters and boot rules read `BRAIN_*` environment variables first, then that file. Shell-profile editing and `--persist-env` are
unnecessary for normal agent use. Restart your CLI to load its settings.
For manual commands outside a client, use the launcher, which reads the same config:

```bash
"$HOME/.agent-brain/bin/brain" validate
```

Windows:

```powershell
& "$env:USERPROFILE\.agent-brain\bin\brain.cmd" validate
```

Use your actual custom vault path. Model choices, account tokens, trust approvals
and unrelated settings are preserved. Nonstandard `CODEX_HOME` or
`CLAUDE_CONFIG_DIR` need the [manual steps](#manual-installation-and-upgrades); guided setup
uses the standard directories beneath the selected home.

## Updates and recovery

Rerun the entry command or download a fresh ZIP. Review the preview, then approve
workflow replacement if needed. With explicit commands, use
`--replace-workflow` for both preview and apply.

Replaced files have before-images and a `manifest.jsonl` mapping their original
paths under `~/Documents/Brain Install Backups/<timestamp>/`. Stop the relevant
agent before restoring a selected backup to its recorded path; preserve later
changes. There is no automatic destructive reset.

Existing notes, templates, Obsidian settings, custom schema, queues, receipts and
local-only files are preserved. Repeated file installation is idempotent;
verification may append private diagnostics. A failed install is reported
explicitly. Correct the cause and rerun with the same options. This is a per-file
atomic installer, not a multi-file transaction. Combined/conflicting hook groups
need a reviewed manual merge. Pause existing scheduled jobs during upgrades and
restore their previous state afterward; setup does not schedule new jobs.

## Troubleshooting

- **Python missing:** install Python 3.10+, enable PATH on Windows, reopen the
  terminal and rerun. `py -3` can also launch a downloaded installer on Windows.
- **CLI missing after installation:** reopen the terminal for the vendor's PATH
  change and run its `--version` command.
- **Folder lacks a Brain index/contract:** choose an empty folder or deliberately
  migrate your vault with the [manual steps](#manual-installation-and-upgrades). Setup will not guess how to merge it.
- **Permission denied or symlink escape:** choose owned, separate directories.
  Do not use broad permission resets or disable client safeguards.
- **Unsupported transcript/failed checkpoint:** keep the error and session.
  An unsupported format cannot produce verified capture.
- **GitHub download/rate limit:** retry later or use the public ZIP method.

PDF extraction optionally needs PyMuPDF in the interpreter used for extraction,
preferably in a project virtual environment. Text and DOCX use the standard library.

Optional extras live in [contrib/](../contrib/README.md): a scheduled Windows audit,
the Obsidian debug-port link checker and the Agent Pulse status plugin. None makes
model calls; checkpoints are written live by the agent in its own session.
[scheduling.md](scheduling.md) has one-line cron, launchd and Task Scheduler entries
for a nightly `hygiene --fix`.

## Manual installation and upgrades

Use the user's existing authorization and preferences. Establish the vault location, participating clients, and whether the optional scheduled audit is wanted before changing the machine. Do not overwrite existing notes, boot files, skills, or settings wholesale.

For guided installation, use the steps above. The included `install.py` implements the file-copy and settings-merge steps below. Preview with `python install.py --client <agent>` (an id from `automation/adapters/`, a comma list such as `claude,kiro`, `both` for claude,codex, or `all` detected agents); apply with the same selection and `--apply`. Use `python3` on macOS/Linux. `--wizard` offers the official installer for a missing CLI. Brain paths are merged into selected-client settings automatically; `--persist-env` is a legacy Windows option. Setup does not log in, enable community plugins or register tasks. Use the remaining checks below after installation.

Existing differing workflow files cause an error before writes. After reviewing the differences, `--replace-workflow` backs up replaced files outside the vault, updates package files, and merges the shared boot block while retaining client-specific text. Existing vault notes/templates/app settings, custom schema, queues and receipts remain untouched. Conflicting hook definitions require a manual merge. Backups and their target manifest are under `~/Documents/Brain Install Backups/`. This is a per-file atomic installer, not a multi-file transaction: after an interrupted install, rerun it with the same options.

### 1. Check prerequisites and preserve existing files

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

### 2. Copy or merge the starter vault

For a new vault, copy `vault/` to the chosen location, default `~/Documents/Brain`. Fill `VAULT-INDEX.md`'s profile only from the user's confirmed information. Rename the example project and update its index/map as appropriate.

For an existing vault, add or merge the contract and guides under `10 - Resources/`, the model daily template, and the dedicated manual template. Reconcile rules in the existing root index without replacing the user's profile, projects, ledgers, priorities, or daily notes. Preserve historical signatures and all frozen archive bytes.

### 3. Install the shared controller and environment

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

### 4. Merge boot rules and install the three skills

Each agent's instructions file is `boot/BRAIN.md`'s `SHARED VAULT RULES` block plus that agent's one-line tail from `automation/adapters/<id>.json`, merged at the manifest's `instructions.path` (for example `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.kiro/steering/agent-brain.md`). `python install.py --render <id>` prints the exact file for a manual merge. Boot files stay outside the vault; each installed block must equal its rendering.

Copy `skills/obsidian-vault/`, `skills/handoff/` and `skills/source-to-vault/` into one skills directory each agent reads, from its manifest's `skills` list; a shared `~/.agents/skills` serves Codex and Copilot once. Every copy of each `SKILL.md` must be byte-identical. Codex's `agents/openai.yaml` is optional UI metadata. Angle-bracket paths in the skills/contract mean resolved environment paths, not literal folder names.

`source-to-vault` preserves original documents and extracts source packets in project folders outside Brain. Text and DOCX need only Python; PDF extraction additionally uses PyMuPDF. Install that dependency only if needed. Extraction does not replace full source review, OCR, or checking citations against the original.

### 5. Install Claude hook adapters

Copy `hooks/vault/` to `~/.claude/hooks/vault/`. Merge the three arrays (SessionStart, PostToolUse, Stop) in `settings/vault-hooks.snippet.json` into the existing `hooks` object in `~/.claude/settings.json`. Replace `{{CLAUDE_DIR}}` inside each `args` entry with the absolute directory. Set `command` to the actual Python executable. The direct-execution form needs no shell quoting and supports Windows without Git Bash. Claude Code 2.1.270+ is the tested minimum. Preserve unrelated hooks/settings, then parse the JSON to verify it.

- SessionStart prints the session brief into context on startup and resume. It reads notes and never writes.
- PostToolUse reports an invalid completed Markdown write with exit 2. It cannot undo the write; the shared controller prevents invalid writes before they happen.
- Stop requests a source-bound checkpoint after substantive work. The request is not evidence that capture happened.

Internal hook failures fail open and are logged. There is no background capture: a session that ends without a checkpoint is not summarized automatically.

### 5b. Install Codex hook adapters

Copy `hooks/vault/` to `~/.codex/hooks/vault/` and merge the three arrays in `settings/codex-hooks.snippet.json` into `~/.codex/hooks.json`, keeping unrelated hooks. Codex takes a shell command string: replace each `script`/`args` pair with `command` set to the quoted Python executable, the script's absolute path and its two arguments (`codex <Event>`). Codex runs it with `$SHELL -lc` on macOS/Linux and `cmd.exe /C` on Windows, where a path containing `%` or `"` cannot be quoted safely. Hooks are on by default (`[features].hooks`); Codex lists new or changed hooks for review, so open `/hooks` once and trust the three Agent Brain entries.

- SessionStart (startup, resume) prints the session brief, which Codex adds as developer context, and records the session's git baseline.
- PostToolUse on `apply_patch` validates vault notes the patch touched (exit 2 with the problems on stderr) and appends the write to the session's turn log under the private state directory. Shell commands are logged only when `~/.agent-brain/config.json` sets `"hooks": {"shell_log": true}` before setup, which adds `Bash` to the matcher at the cost of one Python start per command.
- Stop runs `vault_gate.py`, which needs no transcript: logged writes, git HEAD/remote/dirty-count changes since the baseline, and controller commits since the session's last receipt each count, and a long answer counts only beside five logged tool calls. It asks at most once per ten minutes and never twice for the same delta, as JSON `{"decision": "block", "reason": ...}`, which Codex turns into a continuation prompt. The request is not evidence of capture.

`vaultctl.py gate --agent <id>` and `vaultctl.py validate --hook <id>` run the same logic from a payload on stdin, in the agent's hook dialect.

### 6. Verify the core in an isolated fixture

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

### 7. Configure manual daily notes in Obsidian

Merge `settings/obsidian-daily-notes.json` into `.obsidian/daily-notes.json` and `settings/obsidian-templates.json` into `.obsidian/templates.json`. Enable the built-in Daily Notes and Templates plugins if wanted. Preserve unrelated Obsidian settings.

Daily Notes should use `01 - Daily Notes`, format `MM - MMMM YYYY/YYYY-MM-DD`, and `10 - Resources/Templates/Manual Daily Note Template.md`. Agent-created notes use the separate model template through the controller.

Test creation in a temporary vault: the date/time tokens expand, the five sections and `human` signatures appear, and repeating the command opens the existing note without changing its bytes. Do not infer real UI acceptance from Python tests.

### 8. Optional extras

The scheduled Windows audit, its runtime baseline, the debug-port link checker and the Agent Pulse plugin moved to [contrib/](../contrib/README.md); each folder documents its install and guards. For a plain nightly `hygiene --fix` on any OS, see [scheduling.md](scheduling.md). `vaultctl.py links` is the built-in read-only link audit.

### 9. Verify and record the result

Report the resolved paths, installed clients/components, automated checks, real smoke-test results, and outstanding acceptance separately. Checkpoint the installation through the shared writer. Keep the real vault private if the user elects to version it; this repository remains the shareable template.
