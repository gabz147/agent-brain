"""Streaming Claude/Codex transcript adapters and verifiable coverage receipts."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re

from vault_core import VaultError, atomic_json, file_lock, model_label, now, read_text, sha


def local_stamp(value):
    try:
        stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        return stamp.astimezone()
    except (TypeError, ValueError):
        return None


def clean_text(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    # Defense in depth; callers must still avoid putting credentials in notes.
    text = re.sub(r"(?i)([\"']?(?:api[_-]?key|access[_-]?token|password|secret)[\"']?\s*[:=]\s*)[\"']?[^\s,;\"']+", r"\1[REDACTED]", text)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,})\b", "[REDACTED]", text)
    return text


def blocks(content):
    if isinstance(content, str):
        return content
    output = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind in ("text", "input_text", "output_text"):
            output.append(block.get("text", ""))
        elif kind == "tool_use":
            output.append(json.dumps({k: block.get(k) for k in ("type", "id", "name", "input")}, ensure_ascii=False))
        elif kind == "tool_result":
            output.append(json.dumps({"tool_result": block.get("tool_use_id"), "is_error": block.get("is_error", False),
                                      "content": blocks(block.get("content"))}, ensure_ascii=False))
        elif kind in ("image", "image_url", "input_image"):
            output.append("[Image attachment; binary content omitted]")
        # Never retain hidden reasoning, encrypted reasoning, or analysis.
    return "\n".join(output)


def codex_identity(path, session_id=None):
    with Path(path).open("rb") as source:
        first = json.loads(source.readline())
    if first.get("type") != "session_meta":
        raise VaultError("Codex source is missing its initial session metadata")
    metadata = first.get("payload", {})
    if session_id and metadata.get("id") != session_id:
        raise VaultError("Transcript session id does not match queue entry")
    return metadata


def stream_units(path, provider, session_id=None, fragment_chars=16000):
    """All main-thread evidence, including tool results, in bounded fragments.

    A unit id includes its source line hash and fragment position. Appending to
    a source preserves earlier ids; rewriting a line invalidates its receipt.
    Partial final JSONL records are retried after the source finishes writing.
    """
    offset = 0
    actual_model = None
    actual_session = None
    inherited_sessions = set()
    last_stamp = None
    turn_key = None
    last_user = None
    with Path(path).open("rb") as source:
        for raw in source:
            start, end = offset, offset + len(raw)
            offset = end
            if not raw.endswith(b"\n"):
                break
            if not raw.strip():
                continue
            try:
                item = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise VaultError(f"Malformed transcript JSON at byte {start}") from exc
            kind = item.get("type")
            stamp = local_stamp(item.get("timestamp")) or last_stamp
            if stamp:
                last_stamp = stamp
            role = None
            text = ""
            if provider == "codex":
                payload = item.get("payload", {})
                if kind == "session_meta":
                    if actual_session is None:
                        actual_session = payload.get("id")
                    elif payload.get("id") != actual_session and payload.get("id") not in inherited_sessions:
                        raise VaultError("Unexpected embedded Codex session identity")
                    if payload.get("forked_from_id"):
                        inherited_sessions.add(payload["forked_from_id"])
                elif kind == "turn_context":
                    actual_model = payload.get("model") or actual_model
                elif kind == "event_msg" and payload.get("type") == "user_message":
                    role, text = "user", payload.get("message", "")
                    if last_user and text == last_user[0] and stamp and last_user[1] and abs((stamp - last_user[1]).total_seconds()) < 2:
                        continue  # CLI can mirror a response_item user event.
                    turn_key = str(start)
                    last_user = (text, stamp)
                elif kind == "response_item":
                    subtype = payload.get("type")
                    if subtype == "message" and payload.get("role") == "user":
                        metadata = payload.get("internal_chat_message_metadata_passthrough") or {}
                        kinds = metadata.get("content_item_kinds", [])
                        if kinds and not any(k.startswith("user.") for k in kinds):
                            continue  # Desktop boot/environment injection, not human input.
                        text = blocks(payload.get("content"))
                        if not kinds and text.startswith(("# AGENTS.md instructions", "<environment_context>")):
                            continue
                        if last_user and text == last_user[0] and stamp and last_user[1] and abs((stamp - last_user[1]).total_seconds()) < 2:
                            continue
                        role = "user"
                        turn_key = str(metadata.get("turn_id") or payload.get("id") or start)
                        last_user = (text, stamp)
                    elif subtype == "message" and payload.get("role") == "assistant" and payload.get("channel") != "analysis":
                        role, text = "assistant", blocks(payload.get("content"))
                    elif subtype in ("function_call", "custom_tool_call"):
                        role, text = "tool_call", json.dumps(payload, ensure_ascii=False)
                    elif subtype in ("function_call_output", "custom_tool_call_output"):
                        role, text = "tool_result", json.dumps(payload, ensure_ascii=False)
            elif provider == "claude":
                actual_session = item.get("sessionId") or actual_session
                if item.get("isSidechain") or kind not in ("user", "assistant"):
                    continue
                message = item.get("message", {})
                actual_model = message.get("model") or actual_model
                role, text = kind, blocks(message.get("content"))
                if kind == "user" and item.get("origin", {}).get("kind") == "human":
                    turn_key = str(item.get("uuid") or item.get("timestamp") or start)
            else:
                raise VaultError("Unknown source provider")
            if session_id and actual_session and actual_session != session_id:
                raise VaultError("Transcript session id does not match queue entry")
            if not role or not text.strip():
                continue
            if not stamp:
                raise VaultError("Evidence has no event timestamp")
            text = clean_text(text)
            fragments = max(1, (len(text) + fragment_chars - 1) // fragment_chars)
            digest = sha(raw)
            for number in range(fragments):
                yield {"id": sha(f"{provider}:{start}:{digest}:{number}".encode()), "start": start, "end": end,
                       "line_sha256": digest, "fragment": number, "fragments": fragments,
                       "day": stamp.date().isoformat(), "time": stamp.strftime("%I:%M %p").lstrip("0"),
                       "model": actual_model, "role": role, "turn_key": turn_key,
                       "text": text[number * fragment_chars:(number + 1) * fragment_chars]}


def source_key(provider, session_id):
    if provider not in ("claude", "codex") or not session_id:
        raise VaultError("Provider and source session id are required")
    return sha((provider + ":" + session_id).encode())


def receipt_path(vault, provider, session_id):
    return vault.state / "coverage" / (source_key(provider, session_id) + ".json")


def verified_receipts(vault, provider, session_id):
    path = receipt_path(vault, provider, session_id)
    if not path.exists():
        return []
    data = json.loads(read_text(path))
    valid = []
    for receipt in data.get("receipts", []):
        disposition = receipt.get("disposition")
        if disposition == "trivial":
            if receipt.get("reason") and receipt.get("evidence"):
                valid.append(receipt)
        elif disposition in ("captured", "already_covered"):
            anchors = receipt.get("anchors", [])
            if anchors and all(anchor_valid(vault, anchor) for anchor in anchors):
                valid.append(receipt)
    return valid


def anchor_valid(vault, anchor):
    try:
        info = vault.inspect(anchor["path"])
        text = info["text"] or ""
        fragment = anchor["text"]
        if not isinstance(fragment, str) or len(fragment) < 24:
            return False
        # Proof is a complete daily session fragment, not an mtime or note name.
        return "01 - Daily Notes/" in info["path"] and fragment in text and sha(fragment.encode()) == anchor["sha256"]
    except (KeyError, OSError, VaultError):
        return False


def record_receipt(vault, provider, session_id, receipt):
    path = receipt_path(vault, provider, session_id)
    with file_lock(vault.state / "locks" / (source_key(provider, session_id) + ".receipt.lock")):
        state = json.loads(read_text(path)) if path.exists() else {"version": 2, "provider": provider, "session_id": session_id, "receipts": []}
        if not any(x.get("id") == receipt["id"] for x in state["receipts"]):
            state["receipts"].append(receipt)
            atomic_json(path, state)


def uncovered(vault, path, provider, session_id, max_chars=100000):
    covered = {unit for receipt in verified_receipts(vault, provider, session_id) for unit in receipt["units"]}
    batch, chars, more = [], 0, False
    for unit in stream_units(path, provider, session_id):
        if unit["id"] in covered:
            continue
        if batch and chars + len(unit["text"]) > max_chars:
            more = True
            break
        batch.append(unit)
        chars += len(unit["text"])
    return batch, more


def runtime_model(path, provider, session_id):
    model = None
    for unit in stream_units(path, provider, session_id):
        model = unit.get("model") or model
    return model_label(model)
