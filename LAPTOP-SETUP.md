# Set up the shared agent workflow on a laptop

This installs the same Brain writing rules, daily checkpoints, durable handoffs and document-to-note workflow for Claude Code and Codex. It creates a generic starter vault. Personal notes, credentials, conversations, model subscriptions, third-party plugins, project tools and the workstation's Obsidian theme/companion are not in this public repository. Git pull updates the template; it does not sync personal vault edits between machines.

## 1. Install and sign in to the clients

Use a normal Windows user account and PowerShell. Install Git, Python 3.10 or later, Node.js and the two clients using their official setup instructions: [Codex CLI](https://developers.openai.com/codex/cli/), [Claude Code](https://code.claude.com/docs/en/setup). Install [Obsidian](https://obsidian.md/download) if you want its UI. Git and Python must be on PATH; Node is required by the Claude hook adapters. Install ripgrep (`rg`) for the skills' search examples.

Check the tools in a newly opened terminal:

```powershell
git --version
python --version
node --version
rg --version
codex --version
claude --version
codex login
claude auth login
```

Authenticate on the destination laptop. Do not copy token files from another computer. Select a model available to your account in each client; the workflow records the model that actually runs and does not require a specific paid tier. Scheduled retrospective capture additionally needs a `model` setting in Claude's settings and the CLI flags described in [automation/README.md](automation/README.md).

Release validation used Python 3.11.9, Node 22.15.0, Codex CLI 0.154.0 and Claude Code 2.1.270 on Windows. These are observed versions, not minimum client versions or a promise of account/model availability.

## 2. Clone, preview and install

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\Developer" | Out-Null
Set-Location "$env:USERPROFILE\Developer"
git clone https://github.com/gabz147/agent-brain.git
Set-Location agent-brain
python install.py
python install.py --apply --persist-env
```

The preview lists every planned file. On a fresh account, installation creates:

| Location | Installed content |
|---|---|
| `~/Documents/Brain` | Generic notes, workflow contract, model/manual daily templates and core Obsidian daily settings |
| `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` | Global startup and writing rules |
| Both clients' `skills/` directories | `obsidian-vault`, `handoff`, `source-to-vault` |
| `~/.claude/vault-automation` | Shared controller, schema and optional scheduled runners |
| `~/.claude/hooks/vault` | Claude live checkpoint, validation and queue adapters |
| `~/.claude/settings.json` | Three merged hook entries; unrelated settings retained |

For another vault path, give the same `--vault 'D:\Notes\Brain'` argument to preview and apply. If existing workflow files differ, inspect them before rerunning with `--replace-workflow`. Replaced files get backups; real vault notes are never replaced. Existing hook conflicts and incomplete existing vaults require the manual merge in [INSTALL.md](INSTALL.md). Keep scheduled runners paused while upgrading their files, preserving their previous pause/task state.

The installer sets three Windows user environment variables with `--persist-env`. Also set them in this shell, using your custom vault path if applicable:

```powershell
$env:BRAIN_VAULT_ROOT = Join-Path $env:USERPROFILE 'Documents\Brain'
$env:BRAIN_AUTOMATION_DIR = Join-Path $env:USERPROFILE '.claude\vault-automation'
$env:BRAIN_PYTHON = (Get-Command python).Source
$vaultCtl = Join-Path $env:BRAIN_AUTOMATION_DIR 'vaultctl.py'
```

Restart the terminal application and Obsidian before using the new environment in fresh sessions. If they still inherit old values, sign out and back in to Windows. Do not close another active agent's work as part of setup. Custom `BRAIN_STATE_DIR` or `BRAIN_BACKUPS_DIR` values must name this laptop's private storage; clear stale inherited values deliberately.

On macOS/Linux, `python3 install.py --apply` performs the file installation; omit `--persist-env` and export the three printed variables in your shell profile. Windows Task Scheduler and presence detection are Windows-only. Native Windows is the tested laptop path; WSL is a separate environment with different home/path and scheduling behavior.

## 3. Verify the installation

```powershell
python -m unittest discover -s automation/tests -q
python $vaultCtl validate
python $vaultCtl hygiene
codex login status
claude auth status
```

Expected: tests pass, validation reports `valid`, hygiene reports `verified` with no issues. Investigate issues before claiming success. These checks make no paid model calls. The installer preserves an existing customized schema, so an upgrade may need a reviewed schema/contract merge.

Open `~/Documents/Brain` as a vault in Obsidian. On a fresh vault, Daily Notes and Templates are enabled and configured. Use **Open today's daily note** and confirm the date expands, the note has the five sections and `human` signatures, and opening it a second time leaves it unchanged. Existing vault settings are preserved and may need the manual settings step in INSTALL.md.

## 4. Make both terminal agents demonstrate the workflow

Start `claude` in your home or a project directory. Then start a separate `codex` session. Give each this prompt, one at a time:

> Read your global boot file and the Brain startup notes in full. Resolve the vault and controller paths from the environment. Verify your actual runtime model. Use the shared writer to record a short installation verification in the existing Vault Autonomy Pipeline note and its index, then create a source-bound daily checkpoint from this actual session. Read back the note, daily section and receipt. State any failed check explicitly.

Confirm each agent uses the installed `vaultctl.py`, signs its actual model, and appends a new session without editing the other's old session. Ask the second agent to retrieve the first agent's checkpoint and cite the note. This verifies shared memory across clients. Account permissions and client sandbox rules still apply; grant access to the chosen Brain/controller directories through each client's normal controls if needed. Do not globally disable safeguards to make a smoke test pass.

Claude's Stop hook requests a checkpoint and SessionEnd queues interruptions; a request is not proof of capture. Codex follows its global boot instructions and checkpoints directly. If a transcript format is unsupported, preserve the error/source and leave capture pending instead of inventing a receipt.

## 5. Match the optional background behavior

The workstation uses the optional background components too. To reproduce that behavior, install both scheduled tasks using the exact commands in [automation/README.md, Optional Windows tasks](automation/README.md#optional-windows-tasks), then review definitions, record the runtime baseline, and observe an eligible run. Keep the hidden VBS launcher, Interactive user identity, five-minute idle/fullscreen checks and pause toggle. The installer itself does not register tasks or spend model tokens. An idle deferral is expected while you are actively using the laptop.

For the status orb, copy `plugins/agent-pulse` to `<vault>/.obsidian/plugins/agent-pulse` and enable **Agent Pulse** in Obsidian's community plugins settings. See its [README](plugins/agent-pulse/README.md). Test pause/resume and refresh. The orb displays activity, not verified capture completion.

## 6. Additional skills and ongoing updates

This public template installs only the three Brain skills. If you have a separate private skills backup, install it without overwriting these portable copies; adjust machine-specific paths and install its third-party dependencies separately. Native client plugins and MCP servers need their own installation and authentication. A skill folder alone cannot recreate Blender, browser, video or other project runtimes.

For a template update:

```powershell
Set-Location "$env:USERPROFILE\Developer\agent-brain"
git pull --ff-only
python install.py --replace-workflow
python install.py --apply --replace-workflow --persist-env
```

Use the same custom `--vault` path every time. Review any hook conflict manually. Existing notes/templates and the custom schema are intentionally preserved, so merge relevant guide/schema changes with the shared writer after reviewing them. Re-run the affected smoke checks and checkpoint the result. Keep personal Brain notes outside the public checkout.

## Prompt for the installing CLI agent

> Install this repository's shared Brain workflow for Claude Code and Codex on this laptop. Read LAPTOP-SETUP.md and INSTALL.md completely, inspect existing files, preview install.py and perform the authorized installation. Preserve real notes, client-specific rules, unrelated settings, queues and receipts. Resolve paths for this user. Test the installed controller and hooks, then verify a real checkpoint in each client. If full background behavior is requested, install and verify the documented optional tasks and Agent Pulse. Record actual outcomes and any outstanding UI/login acceptance in Brain; do not claim another machine's tests establish this laptop's runtime behavior.
