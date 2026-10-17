#!/usr/bin/env python
"""Claude SessionStart adapter: prints the session brief into the agent's context. Read-only; fails open silently."""
import datetime as dt
import json
import os
from pathlib import Path
import sys


def main():
    if os.environ.get("VAULT_AUTOMATION") == "1":
        return 0
    try:
        from brain_paths import automation_dir
        directory = automation_dir()
    except Exception:  # a partial install still resolves the legacy default
        directory = Path(os.environ.get("BRAIN_AUTOMATION_DIR") or os.environ.get("VAULT_AUTOMATION_DIR")
                         or Path.home() / ".claude" / "vault-automation").expanduser()
    try:
        sys.stdin.read()  # the payload is not needed; drain it so the client never blocks on the pipe
        sys.path.insert(0, str(directory))
        from vault_core import Vault
        from vault_recall import session_brief
        print(session_brief(Vault(), directory))
        return 0
    except Exception as exc:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with (directory / "hook-errors.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"at": dt.datetime.now().astimezone().isoformat(), "hook": "SessionStart brief",
                                     "error": str(exc)[:800]}) + "\n")
        except OSError:
            pass
        return 0


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
