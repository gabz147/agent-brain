# Obsidian link checker (optional)

`vault_links.mjs` asks a running Obsidian for its own link resolution, headings and blocks over the Chrome DevTools protocol. It reads and never edits notes. For most audits `vaultctl.py links` is enough and needs neither Node nor a debug port.

Copy `vault_links.mjs` into the controller folder (`automation_dir` in `~/.agent-brain/config.json`), start Obsidian with `--remote-debugging-port=9333` on a single vault window, then run:

```text
node <automation_dir>/vault_links.mjs --vault <vault root>
```

Default output is counts plus 20 findings; `--json` returns the full report and `--port` picks another debug port. If Obsidian is already running without the flag, save work and reopen it; never force-close it. `test_vault_links.mjs` runs the checker against fixtures (`node contrib/obsidian-links/test_vault_links.mjs`).
