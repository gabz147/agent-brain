"""Transcript-free hook decisions for any agent: a turn log fed by post-tool hooks, cheap git and vault deltas.

Every entry point fails open. A request never claims capture: only a verified receipt does.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from vault_core import (DEFAULT_AUTOMATION, HERE, SCHEMA, Vault, VaultError, append_jsonl, atomic_json, file_lock,
                        frontmatter, is_daily, iso_normalize, now, read_text, sha, validate)
from vault_hooks import durable_command
from vault_sources import source_key, verified_receipts

PREFIX = "Vault checkpoint requested for session "
WINDOW_MS = 10 * 60 * 1000  # one request per session per ten minutes
TEXT_CHARS, TOOL_EVENTS = 1500, 5  # a long answer counts only beside real tool use
MTIME_FALLBACK_SECONDS = 10
TURNLOG_DAYS = 7


def _key(agent, payload):
    session = payload.get("session_id")
    return (source_key(agent, str(session)), str(session)) if session else (None, None)


def _stamp(value):
    try:
        stamp = dt.datetime.fromisoformat(iso_normalize(value))
        return stamp if stamp.tzinfo else stamp.astimezone()
    except (TypeError, ValueError):
        return None


def git_fingerprint(cwd):
    """HEAD, remote-tracking refs and the dirty-file count; never hashes file contents."""
    try:
        cwd = Path(cwd).resolve()
        if cwd == Path(cwd.anchor) or cwd == Path.home().resolve():
            return "unavailable"
        def git(*args):
            result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=5)
            return result.stdout if result.returncode == 0 else None
        head = git("rev-parse", "HEAD")
        if head is None:
            return "none"
        remotes = git("for-each-ref", "--format=%(objectname)", "refs/remotes") or ""
        status = git("status", "--porcelain") or ""
        return f"{head.strip()}:{sha(remotes.encode())[:12]}:{len([l for l in status.splitlines() if l.strip()])}"
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):  # RuntimeError: Path.home() with no HOME
        return "unavailable"


def patch_paths(command):
    """Files an apply_patch envelope adds, updates, deletes or moves to."""
    return re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", str(command or ""), re.M)


def written_paths(payload, extractors):
    """Paths a post-tool payload names, by the manifest's extractors (dotted keys, `[]` for lists, `apply_patch:` envelopes)."""
    found = []
    for extractor in extractors or []:
        patch = extractor.startswith("apply_patch:")
        keys = (extractor.split(":", 1)[1] if patch else extractor).split(".")
        values = [payload]
        for key in keys:
            many = key.endswith("[]")
            key = key[:-2] if many else key
            values = [v.get(key) for v in values if isinstance(v, dict)]
            if many:
                values = [item for v in values if isinstance(v, list) for item in v]
        for value in values:
            if isinstance(value, str) and value:
                found.extend(patch_paths(value) if patch else [value])
    cwd = Path(payload.get("cwd") or ".")
    return list(dict.fromkeys(str(p if Path(p).is_absolute() else cwd / p) for p in found))


def scratch(path, cwd):
    """A throwaway write: in a scratchpad folder, or under the system temp dir while the session works elsewhere."""
    try:
        path, cwd, temp = Path(path).resolve(), Path(cwd).resolve(), Path(tempfile.gettempdir()).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    if any(part.lower() == "scratchpad" for part in path.parts):
        return True
    return temp in path.parents and not (cwd == temp or temp in cwd.parents)


def recent_vault_writes(vault, seconds=MTIME_FALLBACK_SECONDS):
    """Markdown notes modified in the last few seconds, for payloads that name no path."""
    cutoff = time.time() - seconds
    recent = []
    for path in vault.root.rglob("*.md"):
        try:
            if ".obsidian" not in path.parts and path.stat().st_mtime >= cutoff:
                recent.append(str(path))
        except OSError:
            continue
    return recent


def turnlog_path(vault, key):
    return vault.state / "turnlog" / (key + ".jsonl")


def gate_path(vault, key):
    return vault.state / "gate" / (key + ".json")


def session_start(vault, agent, payload):
    """Record the session's git baseline once and prune old turn logs; return the brief for the agent's context."""
    from vault_recall import session_brief
    key, _ = _key(agent, payload)
    if key:
        path = gate_path(vault, key)
        state = json.loads(read_text(path)) if path.exists() else {}
        if "baseline_git" not in state:
            state.update(baseline_git=git_fingerprint(payload.get("cwd") or "."), baseline_at=now().isoformat())
            atomic_json(path, state)
        cutoff = time.time() - TURNLOG_DAYS * 86400
        for folder, pattern in (("turnlog", "*.jsonl"), ("gate", "*.json")):
            for old in (vault.state / folder).glob(pattern) if (vault.state / folder).is_dir() else []:
                try:
                    if old.stat().st_mtime < cutoff and old != path:
                        old.unlink()
                except OSError:
                    pass
    return session_brief(vault, HERE)


def post_tool(vault, agent, payload, extractors, shell_log=False):
    """Validate vault notes the tool wrote and append the write to the turn log; returns feedback text or ''."""
    paths = written_paths(payload, extractors)
    tool = str(payload.get("tool_name") or "")
    command = (payload.get("tool_input") or {}).get("command") if isinstance(payload.get("tool_input"), dict) else None
    durable = False
    if tool == "Bash" and isinstance(command, str):
        if not shell_log:
            return ""
        durable = any(durable_command(piece) for piece in re.split(r"[;\n]|&&|\|\|", command) if piece.strip())
    elif not paths:
        paths = recent_vault_writes(vault)
    key, _ = _key(agent, payload)
    writes = [p for p in paths if not scratch(p, payload.get("cwd") or ".")]
    if key and (writes or tool == "Bash" or paths):
        append_jsonl(turnlog_path(vault, key), {"at": now().isoformat(), "tool": tool[:60], "paths": writes[:50],
                                                "durable": durable}, vault.state)
    violations = []
    for value in paths:
        try:
            path = vault.path(value)
        except VaultError:
            continue  # outside the vault, not Markdown, or frozen: out of scope
        if not path.is_file():
            continue
        text = read_text(path)
        problems = validate(text, path)
        if not problems:
            fields, _ = frontmatter(text)
            if fields.get("updated_by") in SCHEMA["legacy_signatures"]:
                problems.append("This new write needs the actual runtime model signature; historical body tags must stay unchanged")
        if not problems and is_daily(path):
            from vault_hygiene import daily_structure
            problems = daily_structure(text, path)
        violations.extend(str(path) + ": " + problem for problem in problems)
    if violations:
        return "Vault validation failed:\n" + "\n".join(violations) + "\nUse the shared controller to prepare a valid targeted correction.\n"
    return ""


def controller_commits_since(vault, since):
    """Non-checkpoint controller commits made after `since`, counted from transaction manifests."""
    count = 0
    if not vault.backups.is_dir():
        return 0
    cutoff = since.timestamp() if since else 0
    for entry in os.scandir(vault.backups):
        try:
            if not entry.is_dir() or entry.stat().st_mtime <= cutoff:
                continue
            manifest = json.loads(read_text(Path(entry.path) / "manifest.json"))
            if not str(manifest.get("reason", "")).startswith("Capture "):
                count += 1
        except (OSError, ValueError):
            continue
    return count


def stop(vault, agent, payload, current_ms=None, directory=DEFAULT_AUTOMATION):
    """The checkpoint request text when this session has an unrecorded delta, else ''."""
    if os.environ.get("VAULT_AUTOMATION") == "1" or payload.get("stop_hook_active"):
        return ""
    toggle = Path(directory) / "automation-state.json"
    if toggle.exists():
        state = json.loads(read_text(toggle))
        if state.get("paused") and state.get("scope") == "all":
            return ""
    key, session = _key(agent, payload)
    if not key:
        return ""
    current_ms = current_ms if current_ms is not None else int(time.time() * 1000)
    receipts = verified_receipts(vault, agent, session)
    covered = max((s for s in (_stamp(r.get("at")) for r in receipts) if s), default=None)
    path = gate_path(vault, key)
    with file_lock(vault.state / "locks" / (key + ".gate.lock"), timeout=0.2):
        state = json.loads(read_text(path)) if path.exists() else {}
        fingerprint = git_fingerprint(payload.get("cwd") or ".")
        if covered and state.get("ack_at") != covered.isoformat():
            # A receipt landed since the last look: the work so far is recorded.
            state.update(ack_at=covered.isoformat(), ack_git=fingerprint)
        reference = state.get("ack_git") or state.get("baseline_git")
        if reference is None:
            state.update(baseline_git=fingerprint, baseline_at=now().isoformat())
            reference = fingerprint
        log = turnlog_path(vault, key)
        events = []
        if log.exists():
            for line in read_text(log).splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                at = _stamp(row.get("at"))
                if at and (covered is None or at > covered):
                    events.append(row)
        since = covered or _stamp(state.get("baseline_at"))
        commits = controller_commits_since(vault, since)
        git_changed = "unavailable" not in (fingerprint, reference) and fingerprint != reference
        text = len(str(payload.get("last_assistant_message") or ""))
        work = [row for row in events if row.get("paths") or row.get("durable")]
        substantive = bool(work or commits or git_changed or (text >= TEXT_CHARS and len(events) >= TOOL_EVENTS))
        delta = sha(json.dumps([fingerprint if git_changed else None, len(events), events[-1]["at"] if events else None, commits]).encode())
        if not substantive or state.get("last_delta") == delta or current_ms - state.get("last_fired_ms", 0) < WINDOW_MS:
            atomic_json(path, state)
            return ""
        # Persist only the loop guard; this does NOT claim capture.
        state.update(last_delta=delta, last_fired_ms=current_ms)
        atomic_json(path, state)
    return instruction(vault, agent, session, payload)


def instruction(vault, agent, session, payload):
    transcript, model = payload.get("transcript_path"), payload.get("model")
    command = f'python "{HERE / "vaultctl.py"}" checkpoint --summary --source {agent} --session {session}'
    if transcript and agent in ("claude", "codex"):
        command += f' --transcript "{transcript}"'
    else:
        command += f" --model {model or '<runtime model id>'}"
    contract = vault.root / "10 - Resources/Vault Workflow Contract.md"
    return (f"{PREFIX}{session}. Successful work or substantial findings need a durable checkpoint; a request is not a capture and authorizes no code changes.\n"
            f'If its format is not already in context, load only the "Daily checkpoints and coverage" section of "{contract}"; topic or ledger edits also need its "Shared writer" and "Related notes and ledgers" sections.\n'
            f"Record it in one call: {command} --topic \"...\" --done \"...\" (repeat --done; add --next, --decision, --touched, --open as needed).\n"
            f'Nothing durable: the same command with --trivial "<reason>" instead of the summary flags. Verify the printed receipt.\n')


def emit(dialect, text):
    """(exit code, stdout, stderr) for a Stop request in the agent's hook dialect."""
    if not text:
        return 0, "", ""
    if dialect == "exit2-stdout-async":
        return 2, text, ""
    if dialect in ("json-decision-block", "json-decision-deny"):
        return 0, json.dumps({"decision": "block", "reason": text}), ""
    if dialect == "json-followup":
        return 0, json.dumps({"followup_message": text}), ""
    if dialect == "exit1-stderr":
        return 1, "", text
    return 0, "", ""


def hook(agent, event, payload, adapter, vault=None, config=None):
    """One hook invocation for an agent manifest: (exit code, stdout, stderr). Callers fail open on any exception."""
    vault = vault or Vault()
    hooks = adapter.get("hooks") or {}
    if event == "SessionStart":
        return 0, session_start(vault, agent, payload), ""
    if event == "PostToolUse":
        shell_log = bool(((config or {}).get("hooks") or {}).get("shell_log"))
        feedback = post_tool(vault, agent, payload, hooks.get("paths"), shell_log)
        return (2, "", feedback) if feedback else (0, "", "")
    if event == "Stop":
        return emit(hooks.get("gate_output", "none"), stop(vault, agent, payload))
    return 0, "", ""
