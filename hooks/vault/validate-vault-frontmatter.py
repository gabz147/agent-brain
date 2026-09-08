#!/usr/bin/env python
"""Claude PostToolUse adapter for the schema shared with Codex and hygiene."""
import json
import datetime as dt
import os
from pathlib import Path
import sys

AUTOMATION = Path(os.environ.get("BRAIN_AUTOMATION_DIR") or os.environ.get("VAULT_AUTOMATION_DIR") or Path.home() / ".claude" / "vault-automation").expanduser()
sys.path.insert(0, str(AUTOMATION))
try:
    from vault_core import SCHEMA, Vault, VaultError, frontmatter, is_daily, now, read_text, validate
    from vault_hygiene import daily_structure
except Exception as exc:
    # A missing/broken controller is an internal hook failure, not a reason to
    # block the user's session. Keep a diagnostic for installation repair.
    try:
        AUTOMATION.mkdir(parents=True, exist_ok=True)
        with (AUTOMATION / "hook-errors.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"at": dt.datetime.now().astimezone().isoformat(),
                                 "hook": "PostToolUse import", "error": str(exc)[:800]}) + "\n")
    except OSError:
        pass
    sys.exit(0)


def run():
    payload = json.loads(sys.stdin.read() or "{}")
    inputs = payload.get("tool_input") or {}
    paths = [inputs.get("file_path"), inputs.get("notebook_path")]
    paths.extend(edit.get("file_path") for edit in inputs.get("edits", []) if isinstance(edit, dict))
    vault = Vault()
    violations = []
    for value in set(p for p in paths if isinstance(p, str)):
        try:
            path = vault.path(value)
        except VaultError:
            continue  # outside vault/non-Markdown/frozen content is out of scope
        text = read_text(path)
        problems = validate(text, path)
        if not problems:
            fields, _ = frontmatter(text)
            if fields.get("updated_by") in SCHEMA["legacy_signatures"]:
                problems.append("This new write needs the actual runtime model signature; historical body tags must stay unchanged")
        if not problems and is_daily(path):
            problems = daily_structure(text, path)
        violations.extend(str(path) + ": " + problem for problem in problems)
    if violations:
        sys.stderr.write("Vault validation failed:\n" + "\n".join(violations) + "\nUse the shared controller to prepare a valid targeted correction.\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        sys.exit(run())
    except Exception as exc:
        try:
            with (AUTOMATION / "hook-errors.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"at": now().isoformat(), "hook": "PostToolUse", "error": str(exc)[:800]}) + "\n")
        except OSError:
            pass
        sys.exit(0)
