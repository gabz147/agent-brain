#!/usr/bin/env python
"""Claude Stop adapter. Runs the shared gate in-process; an internal error never wakes or blocks the session."""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import threading

PREFIX = "Vault checkpoint requested for session "
DEADLINE_SECONDS = 10


def log_error(directory, error):
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "hook-errors.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"at": dt.datetime.now().astimezone().isoformat(), "hook": "Stop launcher",
                                 "error": str(error)[:800]}) + "\n")
    except OSError:
        pass


def resolve_directory():
    try:
        from brain_paths import automation_dir
        return automation_dir()
    except Exception:  # a partial install still resolves the legacy default
        return Path(os.environ.get("BRAIN_AUTOMATION_DIR") or os.environ.get("VAULT_AUTOMATION_DIR")
                    or os.path.expanduser("~/.claude/vault-automation"))


def main():
    if os.environ.get("VAULT_AUTOMATION") == "1":
        return 0
    directory = None
    watchdog = None
    try:
        directory = resolve_directory()
        # A controller blocked on an unreadable transcript must not hang until the client kills the hook.
        watchdog = threading.Timer(DEADLINE_SECONDS, lambda: (log_error(directory, f"timeout after {DEADLINE_SECONDS} s"), os._exit(0)))
        watchdog.daemon = True
        watchdog.start()
        sys.path.insert(0, str(directory))
        from vault_hooks import stop_gate
        code, output = stop_gate(json.loads(sys.stdin.read() or "{}"))
        watchdog.cancel()
        # Only the controller's explicit checkpoint request is a wake; anything else fails open.
        if code == 2 and output.startswith(PREFIX):
            print(output)
            return 2
        return 0
    except Exception as exc:
        if watchdog is not None:
            watchdog.cancel()
        if directory is not None:
            log_error(directory, exc)
        return 0


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main())
