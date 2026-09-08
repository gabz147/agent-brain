"""Crash-safe rotation, journals and interruption discovery for both clients."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import time
import uuid

from vault_core import VaultError, append_jsonl, atomic_bytes, atomic_json, file_lock, now, read_text, sha
from vault_capture import Deferred, capture
from vault_sources import codex_identity


def enqueue(directory, entry):
    """One atomic spool file avoids append-versus-rotation races in hooks."""
    if not entry.get("session_id") or not entry.get("transcript_path"):
        raise VaultError("Queue entry lacks source identity")
    entry = dict(entry, source=entry.get("source", "claude"), ts=entry.get("ts", now().isoformat()))
    atomic_json(Path(directory) / "spool" / (uuid.uuid4().hex + ".json"), entry)
    # Legacy plugin activity/counts remain useful. The atomic spool is the
    # durable authority if this compatibility append races with rotation.
    try:
        append_jsonl(Path(directory) / "queue.jsonl", entry, Path(directory) / "state-v2")
    except OSError:
        pass


def discover_codex(vault, directory, session_root=None, lookback_days=7, minimum_idle_seconds=300):
    session_root = Path(session_root or Path.home() / ".codex" / "sessions")
    index_path = vault.state / "codex-discovery.json"
    index = json.loads(read_text(index_path)) if index_path.exists() else {}
    floor = time.time() - lookback_days * 86400
    added = 0
    for path in session_root.rglob("*.jsonl"):
        stat = path.stat()
        if stat.st_mtime < floor or time.time() - stat.st_mtime < minimum_idle_seconds:
            continue
        fingerprint = [stat.st_size, stat.st_mtime_ns]
        if index.get(str(path)) == fingerprint:
            continue
        with path.open("rb") as source:
            first = source.readline()
        try:
            record = json.loads(first)
            session_id = record["payload"]["id"]
        except (ValueError, KeyError) as exc:
            append_jsonl(vault.state / "outcomes.jsonl", {"at": now().isoformat(), "kind": "discovery", "outcome": "failed",
                         "path": str(path), "error": "Malformed Codex session metadata"}, vault.state)
            continue
        if record.get("type") != "session_meta":
            continue
        origin = record["payload"].get("source")
        if isinstance(origin, dict) and origin.get("subagent"):
            append_jsonl(vault.state / "outcomes.jsonl", {"at": now().isoformat(), "kind": "discovery", "outcome": "excluded_subagent",
                         "session_id": session_id, "parent": record["payload"].get("forked_from_id")}, vault.state)
            index[str(path)] = fingerprint
            continue
        enqueue(directory, {"source": "codex", "session_id": session_id, "transcript_path": str(path), "discovered": True})
        # Advance discovery only after its durable queue write succeeds.
        index[str(path)] = fingerprint
        added += 1
    atomic_json(index_path, index)
    return added


def make_batch(directory):
    directory = Path(directory)
    batch = directory / "queue.batch.jsonl"
    existing = batch.read_bytes() if batch.exists() else b""
    legacy = directory / "queue.jsonl"
    if legacy.exists():
        # A read failure is an error, never an empty queue.
        if legacy.stat().st_size:
            os.replace(legacy, directory / ("queue.incoming." + uuid.uuid4().hex + ".jsonl"))
    incoming = sorted(directory.glob("queue.incoming.*.jsonl"))
    spool = directory / "spool"
    paths = sorted(spool.glob("*.json")) if spool.exists() else []
    if not paths and not incoming:
        return batch if batch.exists() else None
    lines = [existing] if existing else []
    for path in incoming:
        lines.append(path.read_bytes())
    for path in paths:
        raw = path.read_bytes()
        # Keep malformed work intact for the failed journal branch.
        lines.append(raw.replace(b"\r", b"").replace(b"\n", b"") + b"\n")
    atomic_bytes(batch, b"".join(lines))
    # Crash here may leave duplicate spool entries; verified receipts dedupe.
    for path in paths + incoming:
        path.unlink()
    return batch


def drain(vault, directory, capture_fn=capture, discover=True, max_attempts=8):
    """Never remove a record until its receipt/journal is durably written."""
    directory = Path(directory)
    summary = {"completed": 0, "partial": 0, "failed": 0, "deferred": 0, "excluded": 0, "attempts": 0}
    with file_lock(vault.state / "locks" / "scheduled.lock", timeout=1):
        if discover:
            summary["discovered"] = discover_codex(vault, directory)
        while summary["attempts"] < max_attempts:
            batch = make_batch(directory)
            if batch is None:
                break
            raw = batch.read_bytes()  # propagate every read error
            lines = raw.splitlines(keepends=True)
            if not lines:
                batch.unlink()
                continue
            remaining = []
            seen = set()
            for position, line in enumerate(lines):
                if summary["attempts"] >= max_attempts:
                    remaining.extend(lines[position:])
                    break
                try:
                    entry = json.loads(line)
                    if not isinstance(entry, dict) or not entry.get("session_id") or not entry.get("transcript_path"):
                        raise ValueError("Missing required source fields")
                except (ValueError, UnicodeError) as exc:
                    append_jsonl(directory / "failed-v2.jsonl", {"at": now().isoformat(), "outcome": "malformed_queue",
                                 "raw": line.decode("utf-8", errors="replace"), "error": str(exc)}, vault.state)
                    summary["failed"] += 1
                    continue
                key = (entry.get("source", "claude"), entry["session_id"], entry["transcript_path"])
                if key in seen:
                    continue
                seen.add(key)
                if entry.get("retry_after") and dt.datetime.fromisoformat(entry["retry_after"]) > now():
                    remaining.append(line)
                    continue
                summary["attempts"] += 1
                try:
                    result = capture_fn(vault, entry)
                    if result.get("disposition") in ("excluded_subagent", "empty_source"):
                        if not result.get("reason"):
                            raise VaultError("Source exclusion needs an explicit reason")
                        append_jsonl(directory / "excluded-v2.jsonl", dict(entry, at=now().isoformat(), result=result), vault.state)
                        summary["excluded"] += 1
                        continue
                    if result.get("disposition") not in ("captured", "already_covered", "trivial"):
                        raise VaultError("Capture returned no verified disposition")
                    if result.get("complete"):
                        # A journal I/O failure must preserve the batch even
                        # though the capture itself can safely replay later.
                        append_jsonl(directory / "processed-v2.jsonl", dict(entry, processed_at=now().isoformat(), result=result), vault.state)
                        summary["completed"] += 1
                    else:
                        remaining.append(line)
                        summary["partial"] += 1
                except Deferred as exc:
                    append_jsonl(vault.state / "outcomes.jsonl", {"at": now().isoformat(), "kind": "queue", "outcome": "deferred",
                                 "session_id": entry["session_id"], "reason": str(exc)}, vault.state)
                    remaining.extend(lines[position:])
                    summary["deferred"] += 1
                    break
                except Exception as exc:
                    entry["retry"] = int(entry.get("retry", 0)) + 1
                    entry["last_error"] = str(exc)[:800]
                    entry["last_attempt"] = now().isoformat()
                    entry["retry_after"] = (now() + dt.timedelta(seconds=min(21600, 300 * 2 ** min(entry["retry"], 8)))).isoformat()
                    append_jsonl(vault.state / "outcomes.jsonl", {"at": now().isoformat(), "kind": "queue", "outcome": "failed",
                                 "session_id": entry["session_id"], "attempt": entry["retry"], "error": str(exc)[:800]}, vault.state)
                    # Repeated errors stay pending; the failure journal is
                    # visibility, never a substitute for recoverable work.
                    append_jsonl(directory / "failed-v2.jsonl", dict(entry, outcome="capture_failed"), vault.state)
                    remaining.append((json.dumps(entry, ensure_ascii=False) + "\n").encode())
                    summary["failed"] += 1
            if remaining:
                atomic_bytes(batch, b"".join(remaining))
                break  # no tight retries of failures, partials or quota limits
            batch.unlink()  # only after every completion/failure journal flush
    return summary
