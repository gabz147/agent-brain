"""Find the installed controller for the hook adapters.

Order: BRAIN_AUTOMATION_DIR (or the legacy VAULT_AUTOMATION_DIR), then the
neutral home's ~/.agent-brain/config.json, then the legacy default directory.
Never raises: an unreadable config simply does not take part.
"""
import json
import os
from pathlib import Path


def config():
    try:
        data = json.loads((Path.home() / ".agent-brain" / "config.json").read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def automation_dir():
    value = os.environ.get("BRAIN_AUTOMATION_DIR") or os.environ.get("VAULT_AUTOMATION_DIR")
    if not value:
        configured = config().get("automation_dir")
        value = configured if isinstance(configured, str) and configured else None
    return Path(value or Path.home() / ".claude" / "vault-automation").expanduser()
