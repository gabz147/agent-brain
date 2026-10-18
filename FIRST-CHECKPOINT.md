# Make your first checkpoint

Open the installed Brain folder as a vault in Obsidian and run **Open today's daily
note**: on a fresh vault it uses the installed human template, and opening it again
keeps existing content. Then, in a **new session** of one of your selected agents,
sign in and review its normal hook/access prompts (on Codex, open `/hooks` once and
trust the three Agent Brain hooks). Paste the prompt for its tier.

**Hook and transcript tier** (Claude Code, Codex CLI):

> Follow your global boot instructions. Read the Brain VAULT-INDEX.md and the
> contract's applicable writing/checkpoint sections. Resolve BRAIN paths and
> verify your actual runtime model from this session. Use the shared vaultctl.py writer to add a
> short installation verification to the existing Vault Autonomy Pipeline note.
> Then record one checkpoint --summary for this actual session transcript to
> append a five-section daily session, and report its receipt ID, model and
> daily anchor. Preserve existing entries. Report any failed check;
> do not claim success from a requested write alone.

**Instructions tier** (GitHub Copilot CLI, Kiro CLI, Qwen Code, Factory Droid, and
any agent without a transcript adapter):

> Follow your global instructions for Agent Brain. Run vaultctl.py session-brief once,
> read the Brain VAULT-INDEX.md and only the contract sections a checkpoint needs.
> Use the shared vaultctl.py writer to add a short installation verification to the
> existing Vault Autonomy Pipeline note. Then record one checkpoint --summary with
> --source set to your agent id, --model set to your actual runtime model id, and the
> summary flags, and report its receipt ID, tier, model and daily anchor. Report any
> failed check; do not claim success from a requested write alone.

The second receipt says `tier: attested` and `model_source: self-report`: it records
the agent's own claim plus cheap git facts, which is weaker evidence than a transcript.

Watch the note appear in Obsidian. Start another session and ask:

> Find the last Brain installation verification using the map and relevant note, and
> tell me what was checked with a link to the note.

If several agents are installed, use a different one for that second prompt.

Also try a greeting in a fresh session. On Claude Code, and on Codex once its hooks
are trusted, the short brief at the top of the session comes from the SessionStart
hook, not from a read. Instructions-tier agents run `vaultctl.py session-brief` once,
and that is the only vault access a greeting should show. Beyond that, the greeting
should not trigger vault reads or a checkpoint. A project task should load the map and
relevant notes; priorities, daily history and contract sections should appear only
when needed. Inspect the tool reads to check this; file installation alone cannot
prove model compliance.

Agents checkpoint **substantive work**, decisions and useful findings. They do not
need to log every short reply. Claude and Codex also get a Stop-hook reminder after
substantive work; instructions-tier agents rely on their instructions. No unattended
capture job or paid model call runs during setup; this manual check uses your own account.

If access is blocked, grant access only to the Brain/controller folders through
the client's normal permissions. Keep the reported error if transcript capture
is unsupported; do not manufacture a successful checkpoint.
