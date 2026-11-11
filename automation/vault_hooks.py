"""Transcript evidence for the shared Stop gate (vault_gate.stop): the latest human turn, what it wrote and ran,
and what its last verified checkpoint already covers. Callers fail open on any exception."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re

from vault_core import DEFAULT_AUTOMATION, Vault, iso_normalize, read_text
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


def transcript_delta(vault, session_id, transcript, current_ms):
    """What the latest human turn of a Claude transcript still owes a checkpoint, or None when it has no human turn.

    Raises OSError when the transcript cannot be read; the caller then falls back to the turn log and git."""
    rows = latest_turn(transcript)
    if not rows:
        return None
    turn_key = str(rows[0].get("uuid") or rows[0].get("timestamp"))
    rows, through = since_acknowledgment(vault, session_id, rows)
    evidence = signals(rows)
    durable = bool(evidence["writes"] or evidence["durable"])
    # After this turn's checkpoint, only later writes or durable commands count.
    substantive = evidence["substantive"] and not (through is not None and not durable)
    # An orchestration still waiting on background agents checkpoints once, at the end.
    if substantive and not durable and pending_agents(rows, current_ms):
        substantive = False
    return {"turn_key": turn_key, "through": through, "substantive": substantive}


def stop_gate(payload, vault=None, directory=DEFAULT_AUTOMATION, current_ms=None):
    """The shared Stop gate for a Claude session, as (exit code, request text): (2, text) asks for a checkpoint."""
    import vault_gate  # lazy: vault_gate imports this module's command heuristics
    text = vault_gate.stop(vault or Vault(), "claude", payload, current_ms, directory, transcript_adapter="claude-jsonl")
    return (2, text) if text else (0, "")
