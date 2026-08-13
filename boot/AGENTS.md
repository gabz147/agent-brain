# Boot Config (Codex / second agent)

This is the pinned boot file for a **second agent** (e.g. Codex CLI) that shares the same vault. It mirrors `CLAUDE.md`: same identity discipline, same vault path, same rules that can't lapse. Place it where your agent auto-loads it (for Codex: `~/.codex/AGENTS.md`).

The only differences from `CLAUDE.md`:

- **Your signature is `codex`** (not `claude`). Stamp `updated_by: codex` on every note you write, and use the `` `(codex)` `` tag in folder indexes, daily-note Index lines, and session headings.
- **You are not covered by the `validate-vault-frontmatter.py` PostToolUse hook** (that hook is Claude Code-specific). So you MUST self-check the five-key frontmatter schema on every write.

Everything else — the startup sequence, the rules that can't lapse, vault health, daily-note discipline, agent signatures — is identical to `CLAUDE.md`. Read `VAULT-INDEX.md` at startup; it is the shared authority for both agents.

> If you only run one agent, you don't need this file. Delete it.
