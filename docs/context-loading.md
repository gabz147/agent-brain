# Context loading

Agent Brain loads context according to the task:

| Task | Additional vault context |
|---|---|
| Greeting or self-contained question | None, unless it establishes something durable |
| Project work or recall | Root map once, then relevant project notes |
| Status or continuation | Relevant priorities section and current project handoff |
| Historical question | Daily Open/Index, then matching sessions |
| Vault write | Applicable contract sections and complete target topic/index notes |
| Full review or workflow audit | Complete requested sources, including the full contract for workflow changes |
| After compaction | Only missing context needed for the current task |

The boot policy stays loaded. Source authorization, verified evidence, secret
handling, shared writes, immutable history and source-bound checkpoints still
apply. A smaller context does not mean skipping an explicitly requested review.

## Measure the package overhead

From the repository root, run `python` on Windows or `python3` on macOS/Linux:

```bash
python3 -c "from pathlib import Path; paths = ['boot/CLAUDE.md', 'boot/AGENTS.md', 'vault/VAULT-INDEX.md']; [print(p, len(Path(p).read_bytes()), 'UTF-8 bytes') for p in paths]"
```

Before this change, the Claude boot file plus index, full contract and priorities
totaled **24,179 UTF-8 bytes**, excluding yesterday's daily note. Codex totaled
24,302 bytes.

| Required package text | Claude | Codex |
|---|---:|---:|
| Previous startup, before yesterday's note | 24,179 bytes | 24,302 bytes |
| New greeting: boot only | 3,355 bytes | 3,369 bytes |
| New project startup: boot plus starter map | 5,558 bytes | 5,572 bytes |

That is about **86% less for a greeting** and **77% less before project-specific
sources**. The regression test caps each new boot file at 3,600 bytes and the
boot plus starter map at 6,000 bytes. These are starter-template measurements;
personalized boot text or a larger root map adds to them. Daily-note growth no
longer increases the required startup reads.

Bytes divided by four is only a rough token estimate. These figures exclude the
client's system prompt, tool schemas, skill metadata, user instructions and task
sources. They are not a billed-token measurement. Writing and detailed recall
still consume tokens when their references are needed.

## Existing installations

Rerun setup and review workflow replacement. The installer updates the marked
shared boot block, skill copies and hook reminder, backing up replaced files.
It preserves personal notes, daily history, settings and client-specific text.
The new boot loading policy explicitly supersedes older blanket startup reads
inside retained Brain notes; task-specific rules still apply. Separate custom
startup instructions outside the shared block need a reviewed manual merge.

Restart the selected client to load the new policy. Test a greeting, a project
request, and the write/recall prompts in [FIRST-CHECKPOINT.md](../FIRST-CHECKPOINT.md).
Check actual tool reads. The tests verify file budgets and upgrade preservation;
they do not prove a particular model follows the policy or measure its billing.
