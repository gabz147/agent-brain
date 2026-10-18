#!/usr/bin/env python
"""Hook adapter for any agent with a hooks manifest: agent-hook.py <agent id> <SessionStart|PostToolUse|Stop>.

Runs the shared transcript-free gate in-process. An internal error never blocks or continues the session:
it is logged to hook-errors.jsonl and the hook exits 0 with no output.
"""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import threading

PREFIX = "Vault checkpoint requested for session "
DEADLINE_SECONDS = 10


def log_error(directory, hook, error):
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "hook-errors.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"at": dt.datetime.now().astimezone().isoformat(), "hook": hook,
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


def main(argv):
    if os.environ.get("VAULT_AUTOMATION") == "1" or len(argv) != 2:
        return 0
    agent, event = argv
    directory = None
    watchdog = None
    try:
        directory = resolve_directory()
        raw = sys.stdin.read()
        watchdog = threading.Timer(DEADLINE_SECONDS, lambda: (log_error(directory, f"{agent} {event}", f"timeout after {DEADLINE_SECONDS} s"), os._exit(0)))
        watchdog.daemon = True
        watchdog.start()
        sys.path.insert(0, str(directory))
        from brain_paths import config
        import vault_adapters
        import vault_gate
        adapter = vault_adapters.load(directory / "adapters")[agent]
        code, out, err = vault_gate.hook(agent, event, json.loads(raw or "{}"), adapter, config=config())
        watchdog.cancel()
        # Only the controller's own request or validation feedback leaves the hook; anything else fails open.
        if event == "Stop" and out and PREFIX not in out and PREFIX not in err:
            return 0
        if out:
            sys.stdout.write(out if out.endswith("\n") else out + "\n")
        if err:
            sys.stderr.write(err)
        return code
    except Exception as exc:
        if watchdog is not None:
            watchdog.cancel()
        if directory is not None:
            log_error(directory, f"{agent} {event}", exc)
        return 0


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
