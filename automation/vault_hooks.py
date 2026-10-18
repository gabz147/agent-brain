"""Fast live-hook decisions; all internal failures are visible and fail open."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import time

from vault_core import DEFAULT_AUTOMATION, DEFAULT_VAULT, HERE, Vault, atomic_json, file_lock, iso_normalize, now, read_text
from vault_sources import source_key, verified_receipts

READ_ONLY = re.compile(r"^\s*(?:ls|dir|pwd|cd|cat|type|head|tail|wc|grep|rg|find|which|where|echo|printf|stat|file|du|df|jq|tree|date|whoami|hostname|git\s+(?:status|log|diff|show|branch|remote|rev-parse|describe)|Get-(?:ChildItem|Content|Item|Location|Command|Process|Date|Service)|Test-Path|Select-String|Measure-Object)\b", re.I)
# One successful durable command is substantive work on its own.
DURABLE = re.compile(r"\b(?:git\s+(?:commit|push|merge|rebase|tag|reset)|gh\s+(?:pr|release)\s+(?:create|merge)"
                     r"|(?:pip3?|npm|pnpm|yarn|winget|choco|cargo)\s+(?:install|add)\b)", re.I)
FILE_MUTATION = re.compile(r"\b(?:Set-Content|Out-File|New-Item|Remove-Item|Copy-Item|Move-Item|sed\s+-i)\b|(?:^|[\s;&|(])(?:cp|mv|rm|mkdir)\s", re.I)
TEMP_PATH = re.compile(r"(?i)[\\/](?:temp|tmp|scratchpad)[\\/]")
PENDING_AGENT_MS = 3 * 3600 * 1000


def durable_command(piece):
    if DURABLE.search(piece):
        return True
    if re.search(r"vaultctl", piece, re.I) and re.search(r"(?<![\w-])(?:commit|restore)(?![\w-])", piece):
        return True
    return bool(FILE_MUTATION.search(piece)) and not TEMP_PATH.search(piece)


def latest_turn(path, initial_bytes=256 * 1024):
    """Expand the tail until the genuine human boundary is found, with no cap."""
    with Path(path).open("rb") as transcript:
        transcript.seek(0, 2)
        size = transcript.tell()
        length = min(initial_bytes, size)
        while length:
            start = max(0, size - length)
            transcript.seek(start)
            if start:
                transcript.readline()  # discard the possibly partial first line
            position = transcript.tell()
            rows = []
            for raw in transcript:
                position += len(raw)
                if not raw.endswith(b"\n"):
                    continue
                try:
                    row = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                if row.get("type") not in ("user", "assistant") or row.get("isSidechain"):
                    continue
                row["_end"] = position  # absolute byte offset, comparable with receipt ranges
                rows.append(row)
            boundary = next((i for i in range(len(rows) - 1, -1, -1) if rows[i].get("type") == "user" and rows[i].get("origin", {}).get("kind") == "human"), None)
            if boundary is not None:
                return rows[boundary:]
            if start == 0:
                return []
            length = min(size, length * 2)
    return []


def signals(rows):
    calls, succeeded, text_chars = {}, set(), 0
    for row in rows[1:]:
        content = row.get("message", {}).get("content", [])
        if isinstance(content, str):
            if row.get("type") == "assistant":
                text_chars += len(content)
            continue
        for block in content:
            kind = block.get("type")
            if kind == "text" and row.get("type") == "assistant":
                text_chars += len(block.get("text", ""))
            elif kind == "tool_use":
                calls[block.get("id")] = block
            elif kind == "tool_result" and not block.get("is_error", False):
                succeeded.add(block.get("tool_use_id"))
    writes, shells, durable = [], [], []
    for call_id in succeeded:
        call = calls.get(call_id, {})
        name, args = call.get("name"), call.get("input", {})
        if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            path = args.get("file_path") or args.get("notebook_path")
            if path and not re.search(r"(?i)[\\/](?:temp|scratchpad)[\\/]", path):
                writes.append(path)
        elif name in ("Bash", "PowerShell"):
            command = args.get("command", "")
            # All command segments must be reads. Do not bless a mixed script
            # just because its first line happens to be Get-Content.
            pieces = [piece for piece in re.split(r"[;\n]|&&|\|\|", command) if piece.strip()]
            if pieces and not all(READ_ONLY.match(piece) for piece in pieces):
                shells.append(command)
            if any(durable_command(piece) for piece in pieces):
                durable.append(command)
    # A long answer alone is a reply, not work: prose counts only alongside real tool use,
    # which is several tool calls or a delegated agent.
    delegated = any(call.get("name") in ("Agent", "Task") for call in calls.values())
    return {"writes": writes, "mutating_shells": len(shells), "durable": len(durable), "text_chars": text_chars,
            "tool_calls": len(calls), "delegated": delegated,
            "substantive": bool(writes or durable or len(shells) >= 3 or (text_chars >= 1500 and (len(calls) >= 5 or delegated)))}


def pending_agents(rows, current_ms):
    """Background agents launched in this turn with no completion notice yet (any terminal status resolves)."""
    launched, resolved = {}, set()
    for row in rows:
        result = row.get("toolUseResult")
        content = row.get("message", {}).get("content", [])
        if isinstance(result, dict) and result.get("isAsync") and result.get("status") == "async_launched" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    launched[block.get("tool_use_id")] = row.get("timestamp")
        if (row.get("origin") or {}).get("kind") == "task-notification":
            resolved.update(re.findall(r"<tool-use-id>([A-Za-z0-9_-]+)</tool-use-id>", json.dumps(content)))
    pending = []
    for tool_id, stamp in launched.items():
        try:
            launched_ms = int(dt.datetime.fromisoformat(iso_normalize(stamp)).timestamp() * 1000)
        except ValueError:
            continue
        if tool_id not in resolved and current_ms - launched_ms < PENDING_AGENT_MS:
            pending.append(tool_id)
    return pending


def since_acknowledgment(vault, session_id, rows):
    """Rows after this turn's verified checkpoint (all rows when none), plus that checkpoint's end offset."""
    if not rows:
        return rows, None
    turn_key = str(rows[0].get("uuid") or rows[0].get("timestamp"))
    completed = vault.state / "live" / (source_key("claude", session_id) + ".json")
    if completed.exists():
        acknowledgment = json.loads(read_text(completed))
        if acknowledgment.get("turn_key") == turn_key and any(r["id"] == acknowledgment.get("receipt_id") for r in verified_receipts(vault, "claude", session_id)):
            through = acknowledgment.get("through") or 0
            return [rows[0]] + [r for r in rows[1:] if r.get("_end", 0) > through], through
    return rows, None


def stop_gate(payload, vault=None, directory=DEFAULT_AUTOMATION, current_ms=None):
    vault = vault or Vault()
    directory = Path(directory)
    if os.environ.get("VAULT_AUTOMATION") == "1" or payload.get("stop_hook_active"):
        return 0, ""
    toggle = directory / "automation-state.json"
    if toggle.exists():
        state = json.loads(read_text(toggle))
        if state.get("paused") and state.get("scope") == "all":
            return 0, ""
    session_id, transcript = payload.get("session_id"), payload.get("transcript_path")
    if not session_id or not transcript:
        return 0, ""
    rows = latest_turn(transcript)
    if not rows:
        return 0, ""
    boundary = rows[0]
    turn_key = str(boundary.get("uuid") or boundary.get("timestamp"))
    key = source_key("claude", session_id)
    current_ms = current_ms if current_ms is not None else int(time.time() * 1000)
    rows, through = since_acknowledgment(vault, session_id, rows)
    evidence = signals(rows)
    durable = bool(evidence["writes"] or evidence["durable"])
    # After this turn's checkpoint, only later writes or durable commands count.
    if through is not None and not durable:
        return 0, ""
    if not evidence["substantive"]:
        return 0, ""
    # An orchestration still waiting on background agents checkpoints once, at the end.
    if not durable and pending_agents(rows, current_ms):
        return 0, ""
    request = vault.state / "requested" / (key + ".json")
    with file_lock(vault.state / "locks" / (key + ".gate.lock"), timeout=0.2):
        previous = json.loads(read_text(request)) if request.exists() else {}
        if (previous.get("turnKey") == turn_key and previous.get("through") == through) or current_ms - previous.get("lastFiredMs", 0) < 600000:
            return 0, ""
        # Persist only the loop guard. This explicitly does NOT claim capture.
        atomic_json(request, {"turnKey": turn_key, "through": through, "lastFiredMs": current_ms, "status": "requested"})
    # Compatibility activity feed for Agent Pulse/Companion. It is never read
    # as coverage. Serialize updates instead of racing on a shared .tmp file.
    with file_lock(vault.state / "locks" / "activity-feed.lock", timeout=0.2):
        feed_path = directory / "stop-state.json"
        feed = json.loads(read_text(feed_path)) if feed_path.exists() else {}
        feed[session_id] = {"turnKey": turn_key, "lastFiredMs": current_ms, "status": "requested"}
        feed = {k: v for k, v in feed.items() if isinstance(v, dict) and current_ms - v.get("lastFiredMs", 0) < 7 * 86400000}
        atomic_json(feed_path, feed)
    instruction = f"""Vault checkpoint requested for session {session_id}. Successful work or substantial findings need a durable checkpoint; a request is not a capture and authorizes no code changes.
If its format is not already in context, load only the "Daily checkpoints and coverage" section of "{vault.root / '10 - Resources/Vault Workflow Contract.md'}"; topic or ledger edits also need its "Shared writer" and "Related notes and ledgers" sections.
Record it in one call, JSON on stdin (Bash heredoc <<'EOF'; use --input <file> only from Windows PowerShell 5.1): python "{HERE / 'vaultctl.py'}" checkpoint --summary --source claude --session {session_id} --transcript \"{transcript}\" with {{"reason": "...", "days": [{{"topic": "...", "sections": {{"What Got Done": ["..."]}}}}], "operations": []}}. The controller fills event day/time, evidence and signature; a turn spanning several days needs one days entry per day (checkpoint-context lists each day's times). Omitted sections become None; add "open_next" only to replace the Open line.
Nothing durable: the same command with --trivial "<reason>" instead of JSON. Topic and handoff edits replace current state; history stays in the daily session.
"""
    return 2, instruction


def run():
    payload = json.loads(sys.stdin.read() or "{}")
    code, output = stop_gate(payload)
    if output:
        print(output)
    return code


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as exc:
        try:
            with (DEFAULT_AUTOMATION / "hook-errors.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"at": now().isoformat(), "hook": "Stop", "error": str(exc)[:800]}) + "\n")
        except OSError:
            pass
        sys.exit(0)
