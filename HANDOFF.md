# Handoff: Agent Brain v2 (agent-agnostic rebuild)

_Written 2026-10-18 by the previous agent session. Read this whole file before touching anything. Delete it from the repo in the final v2 docs pass (milestone 5) or keep it as a changelog; your call._

## Resume

```
cd <checkout of https://github.com/gabz147/agent-brain>
git fetch origin && git checkout claude/friendly-keller-v61ynb   # the v2 working branch, 4 commits ahead of main
python3 -m unittest discover -s automation/tests -q               # expect 138 tests, 3 skipped, all green
```

First action: finish milestone 1 (section 4), which is code-complete but was never reviewed or merged. Then milestone 2.

## 1. What this repo is and what the owner decided

Agent Brain gives terminal coding agents an Obsidian Markdown vault as long-term memory: a stdlib Python controller (`automation/vaultctl.py` and friends) is the only writer; agents read a boot block from their instructions file, read notes on demand, and checkpoint a five-section daily session before handing back. The one-liner in `README.md` installs it from `main`.

The owner's decisions, in their words, from this session:

- **Agent-agnostic.** "I want it to be agent agnostic so u can put any agent u want." Not a Claude Code + Codex pair. Any coding agent with a shell and an instructions file must work.
- **Keep context and tokens low**, but continuity has to work at the start of every session, and the agent must log what it did into the vault.
- **Path 1 first, then v2 on top.** Path 1 (the quick wins) is merged. v2 is what you are continuing.
- **Open decisions the owner has not made** are listed in section 7. Do not decide them silently; pick the recommended default and say so.

## 2. State of the repository

| Where | State |
|---|---|
| `main` | At `e4880ff`, the merge of PR #1 (Path 1). The one-liner installs this. |
| `claude/friendly-keller-v61ynb` | 3 commits ahead of main (`98044e9`, `30a51c8`, `97627ac`) plus the commit that adds this file; see `git log origin/main..HEAD`. Milestone 1, code-complete, **no PR opened yet**. |
| Tests | 138 pass, 3 skipped (optional PyMuPDF). Verified under real Python 3.10 and 3.13 on Linux. CI (`.github/workflows/check.yml`) runs Windows, macOS, Ubuntu on 3.13 plus Ubuntu on 3.10. |
| Published design doc | https://claude.ai/code/artifact/453a8496-d93a-4924-8469-da294314b47d ("Agent Brain v2 Design", two tabs). Private to the owner; ask them to share it or rely on section 5 here, which condenses it. |

### Path 1 (merged in PR #1), so you know what already changed

1. Starter vault cleaned: generic signature rule, template-only Decisions/Dead Ends rows (author history in `docs/examples/author-ledgers.md`), every starter note signed `human`, three dangling wikilinks resolved, folder 08 mapping dropped, the Shared Obsidian Vault Skill note deleted.
2. Dead weight removed: `vaultctl costs`, the Automation Costs note, `templates/`, `automation/audit-prompt.md`, Agent Pulse queue/drain polling (plugin 1.3.0).
3. Neutral home: `install.py` writes `~/.agent-brain/config.json` (vault_root, automation_dir, python, clients). `vault_core.DEFAULT_VAULT` resolves env, then config, then default; `hooks/vault/brain_paths.py` does the same for the controller dir. Env injection into Claude `settings.json` and Codex `config.toml` still happens.
4. Python-only hooks: `hooks/vault/stop-vault-gate.py` replaced the Node shim (10 s watchdog, exit 2 only on the controller's "Vault checkpoint requested" text, fail-open otherwise). Node is no longer a prerequisite; the installer retires the old `.js` hook entry on upgrade. `rewakeSummary` dropped from the snippet.
5. Session brief: `vaultctl.py session-brief` (≤700 bytes: newest daily's Open line, last two session headings, Active Now, hook errors in the last 7 days). `hooks/vault/session-brief.py` injects it on Claude `SessionStart` with matcher `startup|resume` (deliberately not `clear`). Codex boot tail asks for the same command. Stop gate: 1,500 chars of prose counts only beside ≥5 tool calls or a delegated Agent/Task call.
6. Review fixes: newest daily by dated stem (January sorted before December by path), byte-aware brief clipping, unreadable newest note reported, v1 upgrade joins the existing vault instead of creating a second one, stale-client guard (`stale_clients`) refuses a single-client upgrade when the other client holds an older copy, wizard defaults to installed clients, named config.json errors, malformed hook groups no longer traceback.

## 3. Milestone 1 (on the branch, unreviewed): transcript-free checkpoint, Python 3.10 floor

Done in `98044e9`, `30a51c8`, `97627ac`:

- `vaultctl.py checkpoint` no longer needs `--transcript`. Without one: `--source <agent id>` (any `^[a-z0-9][a-z0-9._-]{0,39}$`), `--model <verified runtime id>` (required), and summary flags `--topic`, `--done` (repeatable), `--next`, `--decision`, `--touched`, `--profile`, `--open`, `--day`, `--time`, `--reason`. Built by `flags_payload()`; written by `attested_checkpoint()`; receipt has `tier: attested`, `model_source: self-report`, evidence from `workspace_evidence()` (cwd, git head, dirty-file count). Replaying identical flags returns the same receipt and appends nothing. `--trivial` works the same way. Transcript checkpoints (`--source claude|codex --session --transcript`) are unchanged and remain the stronger tier.
- `vault_capture.validate_proposal` has an attested branch (no unit evidence; days must be ISO; time format only). `vault_sources.source_key` accepts any agent id. `receipt_summary` includes `tier` and `provider`.
- Python floor 3.10: `tomllib` optional (`install.py` leaves Codex `config.toml` alone without it; `toml_bytes` raises a named error), `vault_core.iso_normalize` pads/cuts fractional seconds to six digits before every `fromisoformat`, `automation/tests/test_floor.py` pins the floor with `ast.parse(feature_version=(3,10))`, bootstraps and docs say 3.10+.
- Docs updated: Contract "Daily checkpoints and coverage" (flag form), `skills/obsidian-vault/SKILL.md` (cap raised to 4,300 in `test_guards.py`), both boot files (identical shared block; `boot/AGENTS.md` is 3,592 of a 3,600-byte cap, so trim before adding anything), `automation/README.md`, `README.md`.
- Smoke-tested: Codex-only install into a throwaway home with no `BRAIN_*` env at all; the attested checkpoint, replay, brief and validate all behaved.

### What was in flight when the owner paused

- An adversarial review of these commits was launched as a background workflow and had **not reported** when the session paused. Its results are gone with that session. **Re-run a review yourself** (reproduce-and-refute style: at least the attested path edge cases, the 3.10 floor, and docs consistency) before opening the PR. Known soft spots worth a look: `--time` parsing accepts only `%I:%M %p`; an attested `--open` on a day whose later session already set the Open line is handled by `daily_operation`'s time comparison, confirm it; `since_acknowledgment` reads the attested `live/<key>.json` with `through: None` if an agent names itself `claude` without a transcript (harmless but check).
- Then open the milestone 1 PR to `main` (title suggestion: "v2 milestone 1: checkpoint for any agent, Python 3.10 floor"). The owner merges, or asked me to merge for them on PR #1; ask once.
- Branch rule from the harness: develop on `claude/friendly-keller-v61ynb`; after a PR from it is merged, reset the branch onto `origin/main` (`git checkout -B claude/friendly-keller-v61ynb origin/main`, force-with-lease push) before the next milestone. Never push to another branch.

## 4. What is left: milestones 2 to 5

Each milestone is one PR that leaves the repo installable. Order matters; 2 before 3.

### Milestone 2: one `boot/BRAIN.md` and a data-only adapter registry

Goal: a third agent is a JSON file plus fixtures, never code.

- `boot/BRAIN.md`: the single shared block (keep the `<!-- SHARED VAULT RULES START/END -->` markers or rename to `<!-- AGENT BRAIN START/END -->` and update `install.py`, `vault_hygiene.parity`, tests). Target about 2,000 bytes (today the block is ~3,400). Keep: greetings read nothing; map once for substantive work; brief is navigation not evidence; contract sections on demand; evidence-only; source/config read-only until authorized; check Decisions and Dead Ends; Markdown canonical, no database; never archive unasked; every mutation through the controller; checkpoint before handing back (transcript or `--source/--model` + flags); hooks fail open; nothing runs a model in the background. Add: paths resolve from `BRAIN_*` env, else `~/.agent-brain/config.json`. Tests require the strings "Greetings and self-contained questions: no vault reads" and "replaces older blanket startup/compaction reads" and that the boots name the Contract sections "Daily checkpoints and coverage", "Shared writer", "Related notes and ledgers", "Read and reconcile" (`test_guards.py`, `test_install.py::test_startup_context_budget`). Per-client tails (Claude's `message.model` line, Codex's `turn_context.model` line) become a manifest `instructions.tail` string appended after the block.
- `automation/adapters/<id>.json` plus `automation/adapters/schema.json` (hand-rolled validation, no new dependency). Fields: `id`, `display`, `detect` (dirs, binaries, env), `instructions` (`path`, `strategy`: `marker-block` | `rules-file` | `project-only` | `yaml-read-list`, `tail`), `skills` (list of dirs), `hooks` (null or object, see milestone 3), `transcript_adapter` (`claude-jsonl` | `codex-rollout` | null), `verified_version` (null until fixture-verified on a named version), `notes`.
- `install.py`: `--client` accepts any manifest id, a comma list, `all`, and keeps `both` meaning claude,codex. Detection via `detect`. Render the block into each selected agent's instructions file by strategy (marker-block = today's `BLOCK.sub` merge; rules-file = write `agent-brain.md` whole into a rules dir; project-only = nothing global, `brain init` writes a project `AGENTS.md` **only on request**, bare `vaultctl.py` name, no machine path, with the line "if Agent Brain is not installed, ignore this section"). Copy the three skills into every `skills` dir of every selected agent (dedupe shared dirs). `vault_hygiene.parity` becomes O(N): compare each installed block and skill copy against one canonical rendering, not a hard-coded claude/codex pair. `configured_vault` keeps reading config.json first.
- Per-agent facts (from web research done 2026-10-15; re-verify anything you ship):

| Agent | Global instructions file | Strategy | Skills dirs it reads | Hooks |
|---|---|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | marker-block | `~/.claude/skills`, `.claude/skills` | yes, `~/.claude/settings.json` (already wired) |
| Codex CLI | `~/.codex/AGENTS.md` | marker-block | `~/.agents/skills`, `.agents/skills` (no `~/.codex/skills` in current docs) | yes, `~/.codex/hooks.json` or inline `[hooks]` in config.toml, Claude-shaped, gated by `features.hooks` |
| Copilot CLI | `~/.copilot/copilot-instructions.md` | marker-block | `~/.copilot/skills` or `~/.agents/skills` | yes, `~/.copilot/hooks/*.json`, camelCase events (`sessionStart`, `postToolUse`, `agentStop`); unverified whether a home-dir `*.instructions.md` without `applyTo` applies everywhere |
| Kiro CLI v3 | `~/.kiro/steering/agent-brain.md` | rules-file | `~/.kiro/skills` only | yes, `~/.kiro/hooks/<name>.json`, schema `{"version":"v1","hooks":[…]}` |
| Qwen Code | `~/.qwen/QWEN.md` | marker-block | `~/.qwen/skills` and `~/.agents/skills` (since 0.13.0) | yes, `hooks` in `~/.qwen/settings.json`, Claude-like events |
| Factory Droid | `~/.factory/AGENTS.md` (also reads `~/.agents/AGENTS.md`) | marker-block | `~/.factory/skills`, `~/.agents/skills` | yes, `~/.factory/hooks.json` |
| Cline CLI | `~/.cline/rules/agent-brain.md` | rules-file | `~/.cline/skills`, `~/.agents/skills` | file-based scripts in `~/.cline/hooks/<HookName>`; `TaskComplete` cannot block |
| Gemini CLI | `~/.gemini/GEMINI.md` | marker-block | `~/.gemini/skills` or `~/.agents/skills` | yes, `hooks` in `~/.gemini/settings.json`; SessionStart context only via JSON `hookSpecificOutput.additionalContext`, plain stdout forbidden; consumer access ended 2026-06-18 (successor Antigravity CLI), ship last |
| Cursor CLI | none global; project `.cursor/rules/*.mdc` or `AGENTS.md` | project-only | `~/.cursor/skills`, `~/.agents/skills` | `~/.cursor/hooks.json`; `sessionStart` is fire-and-forget and hooks fire inconsistently across releases; instructions-only until verified |
| OpenCode | `~/.config/opencode/AGENTS.md` | marker-block | `~/.config/opencode/skills`, `~/.agents/skills`, `~/.claude/skills` | none (Bun plugins only) |
| Amp | `~/.config/amp/AGENTS.md` or `~/.config/AGENTS.md` | marker-block | `~/.agents/skills`, `~/.config/amp/skills` | none (plugins only) |
| Goose | `~/.config/goose/.goosehints` | marker-block | `~/.agents/skills` | only inside plugins; cannot deliver text to the model |
| Warp agent CLI | `~/.agents/AGENTS.md` | marker-block | `~/.agents/skills` | none |
| Aider | nothing auto-loaded; `read:` list in `.aider.conf.yml` | yaml-read-list | none | none |

- Tests: every manifest validates; a fresh install for each id into a temp home writes the block where the manifest says; parity passes with one, two and N agents; upgrade from the v1 `boot/CLAUDE.md` block still merges; byte caps hold.

### Milestone 3: Codex hooks and a gate that needs no transcript

- Render Codex `SessionStart` (plain stdout becomes developer context), `PostToolUse` (matchers: shell commands match as `Bash`; apply_patch matches `apply_patch`, `Edit` or `Write`) and `Stop` (must emit JSON `{"decision":"block","reason":"…"}` on exit 0; plain text is invalid) from the registry into `~/.codex/hooks.json`. Codex payload may not carry `model`; treat it as optional. Fixture-test every hook with a synthetic payload (`brain doctor --selftest` idea: replay fixtures against the installed adapter). Claude keeps the tested `asyncRewake` + exit 2 + stdout contract.
- `vaultctl.py gate` (or `brain gate`): decide from the vault manifest delta (`state/manifest.json`: path → sha256 after the last controller write), cheap git signals (HEAD, remote-tracking refs, `git status --porcelain` count; `fingerprint: unavailable` when cwd is `$HOME` or a filesystem root), a hook-fed turn log (`state/turnlog/<session>.jsonl` appended by the post-tool hook; shell logging opt-in via `config.json` `hooks.shell_log`), and the compound text signal. One request per session per 10 minutes, never twice for the same delta, fail open. Replace the Claude-JSONL interpreter in `vault_hooks.py` only after the new gate passes the existing `HookTests` (adapt them).
- `vaultctl.py validate --hook <agent>`: payload normalizer per manifest (written paths key), 10-second mtime fallback, appends the write event to the turn log.
- Per-client emission dialects live in the manifest (`gate_output`: `exit2-stdout-async` | `json-decision-block` | `json-decision-deny` | `json-followup` | `exit1-stderr` | `none`).

### Milestone 4: `brain` package, zipapp, launchers, `get.sh`/`get.ps1`

- Create `brain/` from `automation/` with `__main__.py`; reproducible `python -m zipapp` build to `brain.pyz`; `bin/brain` (sh) and `bin/brain.cmd` (Windows) that probe `py -3`, `python`, `python3`; controller moves to `~/.agent-brain/` with `~/.claude/vault-automation` still honored for upgrades; `vaultctl.py` stays as an alias for one release; `get.sh`/`get.ps1` fetch the pinned release asset, check its sha256 against the release manifest (integrity, not publisher authentication; say so in the README), write launchers, run setup. Drop env injection into client settings once every tier reads config.json. CI builds the zipapp and runs the suite from it on 3.10 and 3.13.

### Milestone 5: cuts, docs, CI

- Move to `contrib/`: the Windows scheduled audit (`invoke-vault-job.ps1`, `nightly-audit.ps1`, `user-busy.ps1`, `run-hidden.vbs`), `vault_runtime.py` and the runtime baseline, `automation/vault_links.mjs` (add a pure-Python `links` command), `plugins/agent-pulse`. Add `docs/scheduling.md` with cron/launchd/schtasks one-liners for `hygiene --fix`.
- Trim `vault/10 - Resources/Vault Workflow Contract.md` to about 9 KB, agent-neutral, loaded only by a `help write` command; drop the per-client command examples.
- One README, `docs/setup.md`, generated `docs/agents/<id>.md` from the registry, FIRST-CHECKPOINT per tier, release workflow publishing `brain.pyz` plus sha256 manifest. Delete this HANDOFF.md.
- Dogfood two weeks with one hook-tier agent, one instructions-only agent and one transcript agent before pointing the one-liner at v2.

## 5. The design in brief (what the judges chose and why)

Three designs were produced and scored by three lenses (end-user install, token economy, correctness/maintenance). The files-only core won every lens (54/54/55 of 70) over an adapter registry on the existing controller (50/48/49) and an MCP-first server (43/45/43).

- **Core, identical for every agent:** Markdown vault; one stdlib Python CLI (`brain`, today `vaultctl.py`) with two load-bearing verbs, `start` (the brief) and `checkpoint`; one instruction block every agent loads; two skills (`brain` = obsidian-vault + handoff merged, and `source-to-vault`).
- **Per agent, data only:** a manifest with instructions path and strategy, skills dirs, hook config and dialect, transcript adapter name. Only the two transcript parsers are per-client code.
- **Tiers:** A, hooks inject context (Claude, Codex, Copilot, Kiro, Qwen, Factory, Cline). B, instructions only (OpenCode, Amp, Goose, Aider, Warp; Gemini and Cursor until verified): the block says "run `session-brief` once unless a brief was already injected" and "checkpoint before handing back"; the CLI nudges with a `checkpoint due` footer once a session has a delta and no receipt, and a `brief not loaded` first line. C, MCP, optional and later (four tools, instructions ≤512 chars, never the policy's only home).
- **Receipts:** tiers `transcript` (units with byte ranges) > `hook` (turn log) > `workspace` (measured deltas) > `attested` (agent's claim). Model-source order: hook payload, then transcript, then self-report, then `unknown-model`. Missed sessions are detected at the next `start` from any agent via the session ledger, git commits since the last receipt and the vault manifest; `checkpoint --for <session>` writes a `Reconstructed:` block; `ack` dismisses.
- **Corrections from the verification pass that the design already folds in:** floor 3.10 not 3.9; Codex hooks confirmed (12 events, Stop needs JSON, Bash/apply_patch matchers); Claude keeps asyncRewake and drops `rewakeSummary`; skills mirror set is `~/.agents/skills` + `~/.claude/skills` (+ `~/.kiro/skills` when Kiro is detected); Copilot does inject MCP instructions behind an allowlist; Node removal touched doctor, the npm shim launcher, CI and three tests; no content hashing of dirty files inside hooks; no "outside-vault edits" flag in the brief (humans edit in Obsidian on purpose); boot block stays near 2,000 bytes, not 345 tokens; keep the compound text signal; never pay for the brief twice; Gemini and Cursor ship last; project `AGENTS.md` on request only.

## 6. Conventions and traps

- Commit messages: imperative title, body in plain prose, no model identifiers in commits or PR text. End each commit with whatever attribution lines your harness's system reminder specifies.
- Every hook fails open: exit 0 and a line in `hook-errors.jsonl` on any internal error; the Stop hook exits 2 **only** with the controller's "Vault checkpoint requested for session …" text.
- Byte caps enforced by tests: each boot file ≤3,600; boot + `vault/VAULT-INDEX.md` ≤6,000; `skills/obsidian-vault/SKILL.md` ≤4,300; `skills/handoff/SKILL.md` ≤1,793; `skills/source-to-vault/SKILL.md` ≤4,260; Contract ≤20,428; Stop instruction template ≤1,246. `skills/obsidian-vault/references/vault-actions.md` must equal the body of `vault/10 - Resources/Vault Actions.md`. Both boot files' shared blocks must be byte-identical.
- The starter vault must stay valid: `python3 automation/vaultctl.py --vault vault --state /tmp/s --backups /tmp/b validate` and `hygiene --no-parity`.
- Daily notes are append-only; the writer enforces it. Never "fix" old sessions.
- `git status --porcelain` on this repo may show CRLF warnings for `.ps1` files after Python writes; harmless (`.gitattributes` normalizes).
- Run the suite with `python3 -m unittest discover -s automation/tests -q`; it spawns the real installer against temp homes and never touches a real vault. Use `set -o pipefail` when chaining `tests | tail && git commit`; one commit in this session slipped out red because of a missing pipefail.
- The earlier review found, and I fixed, these classes of bug; watch for their siblings: path-order vs date-order sorting, char vs byte caps, exceptions escaping fail-open paths, `Path.home()` raising when HOME is unset, installer assumptions that the selected clients are the only installed ones.

## 7. Decisions still the owner's

- CLI name (`brain` vs keeping `vaultctl`) and how long the alias stays.
- Claude Stop: keep the async wake (current) or switch to a synchronous JSON block under the 8-continuation cap.
- `hooks.shell_log` default on (a Python start per shell command) or opt-in.
- Brief default `auto` vs `always`; off by default in cloud/shared sessions?
- Ship `brain mcp` in v2.0 or later.
- `contrib/` vs delete for the Windows audit, CDP link checker and Agent Pulse.
- Python floor 3.10 (done) vs 3.11.
- Whether `brain init` writes a project `AGENTS.md` by default or only on request (recommended: on request).
- Which adapters ship first given verification burden (recommended: Claude, Codex, then Copilot, Kiro, Qwen, Factory; Gemini and Cursor last).

## 8. Owner-facing follow-ups the previous session left open

- Four task cards were queued in the owner's Claude app for the Path 1 work (SessionStart brief, Node removal, vault cleanup, dead-weight removal). All four are done; the owner can dismiss them.
- The published design doc may want a note that milestone 1 is implemented; it is the owner's artifact to share.
