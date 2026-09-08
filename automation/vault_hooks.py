"""Fast live-hook decisions; all internal failures are visible and fail open."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import time

from vault_core import DEFAULT_AUTOMATION, DEFAULT_VAULT, HERE, Vault, atomic_json, file_lock, now, read_text
from vault_sources import source_key, verified_receipts

READ_ONLY = re.compile(r"^\s*(?:ls|dir|pwd|cd|cat|type|head|tail|wc|grep|rg|find|which|where|echo|printf|stat|file|du|df|jq|tree|date|whoami|hostname|git\s+(?:status|log|diff|show|branch|remote|rev-parse|describe)|Get-(?:ChildItem|Content|Item|Location|Command|Process|Date|Service)|Test-Path|Select-String|Measure-Object)\b", re.I)


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
            rows = []
            for raw in transcript:
                if not raw.endswith(b"\n"):
                    continue
                try:
                    row = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                if row.get("type") not in ("user", "assistant") or row.get("isSidechain"):
                    continue
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
    writes, shells = [], []
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
    return {"writes": writes, "mutating_shells": len(shells), "text_chars": text_chars,
            "substantive": bool(writes or len(shells) >= 3 or text_chars >= 1500)}


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
    completed = vault.state / "live" / (key + ".json")
    if completed.exists():
        acknowledgment = json.loads(read_text(completed))
        if acknowledgment.get("turn_key") == turn_key and any(r["id"] == acknowledgment.get("receipt_id") for r in verified_receipts(vault, "claude", session_id)):
            return 0, ""
    evidence = signals(rows)
    if not evidence["substantive"]:
        return 0, ""
    request = vault.state / "requested" / (key + ".json")
    current_ms = current_ms if current_ms is not None else int(time.time() * 1000)
    with file_lock(vault.state / "locks" / (key + ".gate.lock"), timeout=0.2):
        previous = json.loads(read_text(request)) if request.exists() else {}
        if previous.get("turnKey") == turn_key or current_ms - previous.get("lastFiredMs", 0) < 600000:
            return 0, ""
        # Persist only the loop guard. This explicitly does NOT claim capture.
        atomic_json(request, {"turnKey": turn_key, "lastFiredMs": current_ms, "status": "requested"})
    # Compatibility activity feed for Agent Pulse/Companion. It is never read
    # as coverage. Serialize updates instead of racing on a shared .tmp file.
    with file_lock(vault.state / "locks" / "activity-feed.lock", timeout=0.2):
        feed_path = directory / "stop-state.json"
        feed = json.loads(read_text(feed_path)) if feed_path.exists() else {}
        feed[session_id] = {"turnKey": turn_key, "lastFiredMs": current_ms, "status": "requested"}
        feed = {k: v for k, v in feed.items() if isinstance(v, dict) and current_ms - v.get("lastFiredMs", 0) < 7 * 86400000}
        atomic_json(feed_path, feed)
    instruction = f"""Vault checkpoint requested for session {session_id}. Successful work or substantial findings need a durable checkpoint.
Read "{vault.root / '10 - Resources/Vault Workflow Contract.md'}".
Use python "{HERE / 'vaultctl.py'}" checkpoint-context --source claude --session {session_id} --transcript \"{transcript}\" to get the verified model, event date/time and source boundary.
Prepare the daily five-section summary and any targeted topic/index/priority changes, then use vaultctl.py checkpoint with the same source arguments and --input <JSON file>. The controller verifies source evidence, appends a new daily section, snapshots changes and records completion only after read-back. It signs with the actual runtime model (for example opus 5).
Preserve all existing session bytes and old signatures. Use event-local dates for daily paths and actual write date for frontmatter. Update the relevant note/index and ledgers only when the evidence warrants it. No code changes are authorized by this checkpoint request.
If there is no durable work, submit a reasoned trivial disposition through the same checkpoint command. A request is not a completed capture. Keep the checkpoint brief.
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
