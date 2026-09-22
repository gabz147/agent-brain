---
name: agent-brain
description: "Set up or update Agent Brain, the standalone shared Obsidian memory workflow for Claude Code, Codex, or both. Use when installing the system from this repository."
---

# Set up Agent Brain

This repository is the complete distribution. It includes the vault templates,
three everyday workflow skills, shared writer, hooks and optional Windows
automation. Do not require `gabz147/skills` or copy a personal skill library.

Use the full checkout containing this file and `install.py`. If only this skill
file is available, obtain the public `https://github.com/gabz147/agent-brain`
repository in a user workspace first. A standalone copy of these instructions
is not the installed system. Never put the user's vault inside the checkout.

Read [LAPTOP-SETUP.md](LAPTOP-SETUP.md) for prerequisites and installation;
use [INSTALL.md](INSTALL.md) for an existing installation or a manual merge.
Detect the OS. Use the user's chosen clients and vault path; ask only for
choices that remain unknown. Default vault: `~/Documents/Brain`.

Run the repository's installer with Python 3.11+ (`python` on Windows,
`python3` on macOS/Linux). For a user-operated terminal, `install.py --wizard`
provides guided setup. In an agent tool without interactive input, use explicit
arguments: `--client claude|codex|both` and, if chosen, `--vault <path>`.
Run `--doctor`, preview the plan, then use `--apply` within the user's setup
authorization. Missing CLI installation and account login follow the setup
guide; do not claim file installation also authenticated a client.

For upgrades, inspect differing workflow files before `--replace-workflow`.
The installer backs up replacements, merges the shared boot block and preserves
existing notes, unrelated settings, custom schema, queues and receipts. Keep
scheduled jobs from running while their controller is replaced, following
INSTALL.md. Do not reset a vault to the starter template.

Run `--verify` with the same client/vault arguments after installation. Report
the actual paths and checks, then follow [FIRST-CHECKPOINT.md](FIRST-CHECKPOINT.md)
for a real checkpoint and fresh-session recall. Treat account login, agent
behavior and Obsidian UI acceptance separately from file validation.

Everyday work uses the installed `obsidian-vault`, `handoff` and
`source-to-vault` skills. Background capture and Agent Pulse are optional;
configure them only when requested, using the guides in this repository.
Actual notes, credentials, transcripts and runtime state stay private.
