# Make your first checkpoint

Open the installed Brain folder as a vault in Obsidian and run **Open today's daily
note**: on a fresh vault it uses the installed human template, and opening it again
keeps existing content. Then, in a **new session** of
your selected CLI (`claude` or `codex`), sign in and review its normal hook/access
prompts. Paste this:

> Follow your global boot instructions. Read the Brain VAULT-INDEX.md and the
> contract's applicable writing/checkpoint sections. Resolve BRAIN paths and
> verify your actual runtime model from this session. Use the shared vaultctl.py writer to add a
> short installation verification to the existing Vault Autonomy Pipeline note.
> Then record one checkpoint --summary for this actual session transcript to
> append a five-section daily session, and report its receipt ID, model and
> daily anchor. Preserve existing entries. Report any failed check;
> do not claim success from a requested write alone.

Watch the note appear in Obsidian. Start another session and ask:

> Find the last Brain installation verification using the map and relevant note, and
> tell me what was checked with a link to the note.

If several agents are installed, use a different one for that second prompt.

Also try a greeting in a fresh session. On Claude Code the short brief at the
top of the session comes from the SessionStart hook, not from a read. On other agents,
which have no hooks here yet, the instructions have them run `vaultctl.py session-brief`
once, and that is the only vault access a greeting should show. Beyond that, the
greeting should not trigger vault reads or a checkpoint. A project task should load the map and relevant notes; priorities,
daily history and contract sections should appear only when needed. Inspect the
tool reads to check this; file installation alone cannot prove model compliance.

Agents checkpoint **substantive work**, decisions and useful findings. They do
not need to log every short reply. Claude also has a Stop-hook reminder. Codex
uses startup instructions and the shared writer directly. No unattended capture
job or paid model call runs during setup; this manual check uses your own account.

If access is blocked, grant access only to the Brain/controller folders through
the client's normal permissions. Keep the reported error if transcript capture
is unsupported; do not manufacture a successful checkpoint.
