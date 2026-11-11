# Optional extras

Agent Brain works without anything here. Setup never installs these; each folder says how to add it by hand. None of them calls a model.

| Folder | What it is |
|---|---|
| [windows-audit/](windows-audit/README.md) | A Task Scheduler job that runs the nightly `hygiene` audit behind idle, fullscreen and pause guards, plus `vault_runtime.py`, which records and checks an approved baseline of that task and the vault hooks. Windows only. |
| [obsidian-links/](obsidian-links/README.md) | `vault_links.mjs`, a link checker that drives a running Obsidian over its debug port and uses Obsidian's own parser. `vaultctl.py links` is the built-in pure-Python audit; use this one when you need Obsidian's exact resolution. Needs Node 22+. |
| [obsidian-cli/](obsidian-cli/README.md) | `obsidian_read.py`, read-only observations through Obsidian's native CLI (file links, backlinks, properties, local recovery history, a write preflight). Needs Obsidian 1.12.7+ running with its CLI enabled. `vaultctl.py validate` and `links` stay authoritative. |
| [agent-pulse/](agent-pulse/README.md) | An Obsidian plugin with a status orb, an automation pause toggle and a soft refresh for agent edits. Its indicators are not capture receipts. |

For a scheduled `hygiene --fix` on macOS, Linux or Windows without these scripts, see [docs/scheduling.md](../docs/scheduling.md).
