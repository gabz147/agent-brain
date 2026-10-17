#!/usr/bin/env python
"""Claude Stop adapter. Runs the shared gate in-process; an internal error never wakes or blocks the session."""
import datetime as dt
import json
import os
from pathlib import Path
import sys

PREFIX = "Vault checkpoint requested for session "


def log_error(directory, error):
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "hook-errors.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"at": dt.datetime.now().astimezone().isoformat(), "hook": "Stop launcher",
                                 "error": str(error)[:800]}) + "\n")
    except OSError:
        pass


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
        sys.path.insert(0, str(directory))
        from vault_hooks import stop_gate
        code, output = stop_gate(json.loads(sys.stdin.read() or "{}"))
        # Only the controller's explicit checkpoint request is a wake; anything else fails open.
        if code == 2 and output.startswith(PREFIX):
            print(output)
            return 2
        return 0
    except Exception as exc:
        log_error(directory, exc)
        return 0


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
