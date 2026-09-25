# Set up Agent Brain

Agent Brain is a standalone public vault workflow. You need this repository only.
It installs a generic Obsidian vault and three related skills for Claude Code,
Codex, or both, without anyone's personal notes or unrelated skills.

`gabz147/skills` is a separate personal backup and is not needed. For setup
through an agent, open this checkout and ask it to follow [SKILL.md](SKILL.md).
The root `agent-brain` skill handles setup; the three skills under `skills/`
handle everyday vault work after installation.

## Prerequisites

- **Obsidian**, already installed: [official download](https://obsidian.md/download).
- **Python 3.11+**, on PATH: [official downloads](https://www.python.org/downloads/).
  On Windows select Add Python to PATH. On Linux use your distribution's Python
  package if it is new enough. Reopen the terminal afterward.
- **Node.js 22+** for Claude's hooks: [official LTS download](https://nodejs.org/en/download).
  Codex-only setup does not need Node unless your Codex installation does.
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

Copy the command for your system from the [README](README.md#install).

1. Choose Claude Code, Codex, or both.
2. Accept the default vault folder (`~/Documents/Brain`) or choose another.
3. Resolve missing prerequisites. If offered, approve the official CLI installer.
   Sign-in happens separately when you start the client.
4. Review the planned files. Differing workflow files require a replacement
   choice and are backed up. Confirm application of the plan.
5. Open the printed folder in Obsidian. Start a fresh CLI session and follow
   [FIRST-CHECKPOINT.md](FIRST-CHECKPOINT.md). A copy is saved beside the controller.

Startup rules ask agents to checkpoint substantive work, findings, decisions and
handoffs. Claude also gets a Stop-hook reminder. Codex uses the instructions and
shared writer directly. Test writing and next-session recall with the guide;
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

For explicit noninteractive setup, preview then apply. Substitute `claude` or
`both` for `codex`, and use `python` on Windows:

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
| `~/.claude/CLAUDE.md`, if selected | Claude Brain startup/writing rules |
| `~/.codex/AGENTS.md`, if selected | Codex Brain startup/writing rules |
| Selected clients' `skills/` folders | `obsidian-vault`, `handoff`, `source-to-vault` only |
| `~/.claude/vault-automation` | Shared writer/schema and first-checkpoint guide; used by either client |
| `~/.claude/hooks/vault`, if selected | Claude reminder, validation and interruption queue adapters |
| Selected clients' configuration | Brain paths/interpreter merged with existing settings |

The shared controller retains its established `.claude/vault-automation` location
for compatibility. Codex-only setup uses that folder but does not install Claude,
its boot file, its skills or its hooks.

Brain paths are stored in Claude's `settings.json.env` and Codex's
`shell_environment_policy.set`. Shell-profile editing and `--persist-env` are
unnecessary for normal agent use. Restart your CLI to load its settings.
For manual commands outside a client, explicitly supply your vault:

```bash
python3 "$HOME/.claude/vault-automation/vaultctl.py" --vault "$HOME/Documents/Brain" validate
```

Windows:

```powershell
python "$env:USERPROFILE/.claude/vault-automation/vaultctl.py" --vault "$env:USERPROFILE/Documents/Brain" validate
```

Use your actual custom vault path. Model choices, account tokens, trust approvals
and unrelated settings are preserved. Nonstandard `CODEX_HOME` or
`CLAUDE_CONFIG_DIR` need the manual steps in [INSTALL.md](INSTALL.md); guided setup
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

- **Python missing:** install Python 3.11+, enable PATH on Windows, reopen the
  terminal and rerun. `py -3` can also launch a downloaded installer on Windows.
- **Node missing:** install Node LTS and reopen the terminal. It is needed for
  Claude hooks, not the Python writer.
- **CLI missing after installation:** reopen the terminal for the vendor's PATH
  change and run its `--version` command.
- **Folder lacks a Brain index/contract:** choose an empty folder or deliberately
  migrate your vault with INSTALL.md. Setup will not guess how to merge it.
- **Permission denied or symlink escape:** choose owned, separate directories.
  Do not use broad permission resets or disable client safeguards.
- **Unsupported transcript/failed checkpoint:** keep the error and session.
  An unsupported format cannot produce verified capture.
- **GitHub download/rate limit:** retry later or use the public ZIP method.

PDF extraction optionally needs PyMuPDF in the interpreter used for extraction,
preferably in a project virtual environment. Text and DOCX use the standard library.

The optional Windows audit task and Agent Pulse are documented in
[automation/README.md](automation/README.md) and
[the plugin guide](plugins/agent-pulse/README.md). Neither makes model calls;
checkpoints are written live by the agent in its own session.
