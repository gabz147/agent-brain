#!/usr/bin/env python3
"""PostToolUse hook: validate YAML frontmatter on vault markdown notes.

Reads a Claude Code PostToolUse hook JSON payload from stdin, and if the
tool wrote/edited a .md file under the vault root, validates its
frontmatter block against the vault's schema:

    status:     active | completed | parked | idea | archived
    project:    any kebab-case slug (see PROJECT_ALLOWLIST below)
    type:       index | reference | guide | plan | log
    updated_by: claude | codex | human
    updated:    YYYY-MM-DD

All five keys are required, no other keys are allowed, and daily notes
(01 - Daily Notes/YYYY-MM-DD.md) must have type: log, status: active,
project: personal.

updated_by / updated are the agent signature: whichever agent last wrote
the note stamps itself and the date.

On a genuine, confidently-detected violation: exit 2, message on stderr.
On anything else (out-of-scope path, unreadable file, unparseable
frontmatter, unexpected input shape, internal bug): exit 0, silently.

--------------------------------------------------------------------------
PORTABILITY: the vault root is read from the BRAIN_VAULT_ROOT environment
variable. If it is unset, the fallback below is used -- EDIT the fallback
to your own vault path, or (better) set BRAIN_VAULT_ROOT once in your
environment so every tool agrees.
--------------------------------------------------------------------------
"""

import sys
import json
import re
import os

# EDIT this fallback, or set BRAIN_VAULT_ROOT in your environment.
VAULT_ROOT = os.environ.get(
    "BRAIN_VAULT_ROOT",
    os.path.join(os.path.expanduser("~"), "Documents", "Brain"),
)

STATUS_VALUES = {"active", "completed", "parked", "idea", "archived"}

# project: by default any lowercase kebab-case slug is accepted, so a new
# vault's notes are never rejected just for using a project name the hook
# has not heard of. To LOCK the vault to a fixed set of projects, fill in
# PROJECT_ALLOWLIST with your slugs (e.g. {"personal", "meta", "work"}) and
# the hook will enforce exactly those instead.
PROJECT_ALLOWLIST = set()  # empty => accept any kebab-case slug
PROJECT_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

TYPE_VALUES = {"index", "reference", "guide", "plan", "log"}
UPDATED_BY_VALUES = {"claude", "codex", "human"}
REQUIRED_KEYS = {"status", "project", "type", "updated_by", "updated"}

DAILY_NOTE_FILENAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$", re.IGNORECASE)
UPDATED_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_path(p):
    """Normalize separators + case + trailing slash for comparison."""
    return p.replace("/", "\\").rstrip("\\").lower()


def extract_frontmatter(content):
    """Parse the leading '---' fenced block into a dict of key -> value.

    Returns None if no well-formed frontmatter fence is found at the very
    top of the file (treated as "cannot parse" -> caller should not block).
    """
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines:
        return None
    if lines[0].strip() != "---":
        return None

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None

    result = {}
    for line in lines[1:end_idx]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            if key in REQUIRED_KEYS and value[:1] in ("[", "{", "|", ">"):
                return None
            hash_idx = value.find(" #")
            if hash_idx != -1:
                value = value[:hash_idx].strip()
        if key:
            result[key] = value
    return result


def is_daily_note(file_path):
    norm = file_path.replace("/", "\\")
    parts = [seg for seg in norm.split("\\") if seg]
    if not parts:
        return False
    filename = parts[-1]
    if not DAILY_NOTE_FILENAME_RE.match(filename):
        return False
    for seg in parts[:-1]:
        if seg.strip().lower() == "01 - daily notes":
            return True
    return False


def project_is_valid(project):
    if PROJECT_ALLOWLIST:
        return project in PROJECT_ALLOWLIST
    return bool(project) and bool(PROJECT_SLUG_RE.match(project))


def validate(frontmatter, file_path):
    """Return a violation message string, or None if frontmatter is valid."""
    extra_keys = sorted(k for k in frontmatter.keys() if k not in REQUIRED_KEYS)
    if extra_keys:
        return (
            f"frontmatter has undeclared key(s) {extra_keys} "
            f"-- only allowed keys are: status, project, type, updated_by, updated"
        )

    missing_keys = sorted(k for k in REQUIRED_KEYS if k not in frontmatter)
    if missing_keys:
        return (
            f"frontmatter missing required key(s) {missing_keys} "
            f"-- status, project, type, updated_by, updated must all be present"
        )

    status = frontmatter.get("status")
    project = frontmatter.get("project")
    type_ = frontmatter.get("type")
    updated_by = frontmatter.get("updated_by")
    updated = frontmatter.get("updated")

    if status not in STATUS_VALUES:
        return (
            f"invalid 'status: {status}' "
            f"-- allowed values: {sorted(STATUS_VALUES)}"
        )
    if not project_is_valid(project):
        if PROJECT_ALLOWLIST:
            return (
                f"invalid 'project: {project}' "
                f"-- allowed values: {sorted(PROJECT_ALLOWLIST)}"
            )
        return (
            f"invalid 'project: {project}' "
            f"-- must be a lowercase kebab-case slug (e.g. my-project)"
        )
    if type_ not in TYPE_VALUES:
        return (
            f"invalid 'type: {type_}' "
            f"-- allowed values: {sorted(TYPE_VALUES)}"
        )
    if updated_by not in UPDATED_BY_VALUES:
        return (
            f"invalid 'updated_by: {updated_by}' "
            f"-- allowed values: {sorted(UPDATED_BY_VALUES)} "
            f"(stamp whichever agent wrote this note)"
        )
    if not UPDATED_DATE_RE.match(updated or ""):
        return (
            f"invalid 'updated: {updated}' "
            f"-- must be a YYYY-MM-DD date"
        )

    if is_daily_note(file_path):
        if type_ != "log":
            return (
                f"daily note requires 'type: log' but found 'type: {type_}'"
            )
        if status != "active":
            return (
                f"daily note requires 'status: active' but found 'status: {status}'"
            )
        if project != "personal":
            return (
                f"daily note requires 'project: personal' but found 'project: {project}'"
            )

    return None


def extract_file_path(tool_input):
    for key in ("file_path", "path", "filePath", "file", "notebook_path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def run():
    raw = sys.stdin.read()
    if not raw or not raw.strip():
        return 0

    data = json.loads(raw)
    if not isinstance(data, dict):
        return 0

    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    file_path = extract_file_path(tool_input)
    if not file_path:
        return 0

    file_path = os.path.normpath(file_path)
    norm_path = normalize_path(file_path)
    norm_vault = normalize_path(VAULT_ROOT)

    if not norm_path.endswith(".md"):
        return 0
    if not (norm_path == norm_vault or norm_path.startswith(norm_vault + "\\")):
        return 0

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    frontmatter = extract_frontmatter(content)
    if frontmatter is None:
        return 0

    violation = validate(frontmatter, file_path)
    if violation:
        sys.stderr.write(f"Vault frontmatter violation: {violation}\n")
        sys.exit(2)

    return 0


if __name__ == "__main__":
    try:
        exit_code = run()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
    else:
        sys.exit(exit_code if isinstance(exit_code, int) else 0)
