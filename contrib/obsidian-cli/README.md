# Read-only Obsidian CLI helper

`obsidian_read.py` asks a running Obsidian (1.12.7+, command line interface enabled in Settings > General) for what it knows about the vault: `diagnostics`, `link-audit`, `backlinks "<vault-relative.md>"`, `properties`, `history` and `preflight`. It selects the vault by Obsidian's own ID, verifies the native path on every request, refuses unsafe paths and bounds each call. It never writes a note.

Setup does not install it. To use it, copy `obsidian_read.py` next to the controller (the `automation_dir` in `~/.agent-brain/config.json`) or run it from this folder:

```text
python obsidian_read.py diagnostics
python obsidian_read.py link-audit
```

Limits: native file links include Archive and carry no heading, block or freshness check, and `preflight` compares hashes around a history read without locking anything. The controller's `vaultctl.py validate`, `vaultctl.py links` and expected-hash commits stay authoritative. Tests: `python contrib/obsidian-cli/test_obsidian_read.py`.
