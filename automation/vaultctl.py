"""Single entry point for both agents and unattended vault workflows."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys

from vault_core import (DEFAULT_AUTOMATION, DEFAULT_BACKUPS, DEFAULT_STATE, DEFAULT_VAULT, HERE, Conflict, Vault, VaultError,
                        ISO_TIME, append_jsonl, atomic_json, file_lock, format_note_time, frontmatter,
                        is_daily, model_label, now, parse_note_time, read_text, sha, validate)
from vault_sources import source_key, stream_units, uncovered, verified_receipts
from vault_capture import apply_proposal
from vault_hygiene import hygiene
from vault_recall import consolidate_context, fact_freshness, mark_consolidated, recall_eval, session_brief


def load_input(path):
    # Windows PowerShell pipes may prepend a UTF-8 BOM; json.loads rejects it.
    return json.loads((read_text(path) if path else sys.stdin.read()).lstrip("﻿"))


def format_times(vault, apply=False):
    operations, changes = [], []
    for path in vault.notes():
        info = vault.inspect(path)
        fields, _ = frontmatter(info["text"])
        value = fields.get("updated", "")
        if not ISO_TIME.fullmatch(value):
            continue
        changes.append({"path": info["path"], "before": value,
                        "after": format_note_time(parse_note_time(value))})
        operations.append({"path": info["path"], "expected_sha256": info["sha256"], "format_updated": True})
    receipts = []
    if apply:
        for start in range(0, len(operations), 100):
            receipts.append(vault.commit(operations[start:start + 100], "automation", "Format note timestamps without changing their instants or authors"))
    return {"outcome": "formatted" if apply else "preview", "changes": changes,
            "transactions": [r["transaction_id"] for r in receipts if r.get("transaction_id")]}


def daily_context(vault, path):
    """Navigation only, never a substitute for reading requested history.

    The writer independently reads and protects all existing daily bytes.
    Return every session heading, with line numbers, without repeating bodies.
    """
    resolved = vault.path(path)
    if not is_daily(resolved):
        raise VaultError("daily-context requires a dated daily-note path")
    entry = vault.inspect(path)
    text = entry.pop("text")
    entry.update(scope="Navigation only; session bodies and Index bullets omitted",
                 exists=text is not None, open_next=None, sessions=[])
    if text is None:
        return entry
    problems = validate(text, resolved)
    if problems:
        raise VaultError("Invalid daily note: " + "; ".join(problems))
    # Fenced examples are not actual session headings.
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not line.strip()[len(token):].strip():
                fence = None
            continue
        if fence:
            continue
        if line.startswith("**Open for tomorrow:**"):
            entry["open_next"] = line
        match = re.match(r"^## Session (\d+)\b", line)
        if match:
            entry["sessions"].append({"line": number, "heading": line})
    return entry


def receipt_summary(receipt):
    """Only presentation changes; checkpoint persists and verifies full receipts."""
    return {**{key: receipt.get(key) for key in
               ("id", "disposition", "writer_model", "transaction_id", "tier", "provider")},
            "source_units": len(receipt.get("units", [])),
            "anchors": [{"path": a["path"], "sha256": a["sha256"],
                         "heading": a["text"].splitlines()[0]}
                        for a in receipt.get("anchors", [])]}


def live_units(args):
    units = list(stream_units(args.transcript, args.source, args.session))
    if not units:
        raise VaultError("No transcript evidence")
    turn = units[-1].get("turn_key")
    if not turn:
        raise VaultError("No human-origin turn boundary")
    return [u for u in units if u.get("turn_key") == turn]


def day_times(units):
    """First and last source-local event time for each day in the turn."""
    spans = {}
    for unit in units:
        spans.setdefault(unit["day"], [unit["time"], unit["time"]])[1] = unit["time"]
    return [{"day": day, "first": first, "last": last} for day, (first, last) in sorted(spans.items())]


def fill_days(payload, units):
    """A single-day turn supplies its day; an omitted time is that day's last event."""
    days = sorted({u["day"] for u in units})
    for entry in payload.get("days", []):
        if not entry.get("day") and len(days) == 1:
            entry["day"] = days[0]
        if entry.get("day") and not entry.get("time"):
            times = [u["time"] for u in units if u["day"] == entry["day"]]
            if times:
                entry["time"] = times[-1]


def default_evidence(units):
    unit = next((u for u in units if len(re.sub(r"\s", "", u["text"][:120])) >= 8), units[0])
    return [{"unit_id": unit["id"], "quote": unit["text"][:120]}]


def refuse_trivial(vault, args):
    """A trivial disposition must not hide durable work done since this turn's last checkpoint."""
    if args.source != "claude" or not args.transcript:
        return
    from vault_hooks import latest_turn, signals, since_acknowledgment
    rows, _ = since_acknowledgment(vault, args.session, latest_turn(args.transcript))
    evidence = signals(rows) if rows else {"writes": [], "durable": 0}
    if evidence["writes"] or evidence["durable"]:
        raise VaultError(f"--trivial refused: this turn has {len(evidence['writes'])} vault/project writes and "
                         f"{evidence['durable']} durable commands since its last checkpoint; record them as a captured session")


def checkpoint(vault, args, payload):
    units = live_units(args)
    signer = model_label(next((u["model"] for u in reversed(units) if u.get("model")), None))
    # Verification tool output grows the transcript between retries. Bind the
    # same prepared checkpoint to its human turn and payload, not that tail.
    prepared = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    capture_id = "live-" + sha((source_key(args.source, args.session) + ":" + units[0]["id"] + ":" + prepared).encode())
    payload = copy.deepcopy(payload)
    fill_days(payload, units)
    proposal = {"disposition": payload.get("disposition", "captured"), "reason": payload.get("reason", "Interactive checkpoint"),
                "evidence": payload.get("evidence") or default_evidence(units),
                "days": payload.get("days", []), "operations": payload.get("operations", []), "anchors": payload.get("anchors", [])}
    current_ids = {u["id"] for u in units}
    receipt = next((r for r in verified_receipts(vault, args.source, args.session)
                    if r["id"] == capture_id and all(unit in current_ids for unit in r["units"])), None)
    if receipt is None:
        receipt = apply_proposal(vault, proposal, signer, units, args.source, args.session, capture_id)
    # A separate acknowledgment is written only after the daily receipt passes.
    atomic_json(vault.state / "live" / (source_key(args.source, args.session) + ".json"),
                {"turn_key": units[-1]["turn_key"], "receipt_id": receipt["id"], "status": receipt["disposition"],
                 "completed_at": now().isoformat(), "through": max(r["end"] for r in receipt["ranges"])})
    return receipt


SUMMARY_FLAGS = (("done", "What Got Done"), ("next", "What's Still In Progress"), ("decision", "Decisions Made"),
                 ("touched", "Notes Touched"), ("profile", "Profile Updates"))


def event_time(value):
    """3:42 PM, 3:42 pm or 15:42 as the daily heading's 3:42 PM; anything else is left for validation to name."""
    for form in ("%I:%M %p", "%H:%M"):
        try:
            return dt.datetime.strptime(value.strip().upper(), form).strftime("%I:%M %p").lstrip("0")
        except ValueError:
            pass
    return value


def flags_payload(args):
    """The checkpoint JSON an agent would otherwise write, built from repeatable flags."""
    if args.input:
        raise VaultError("Use the summary flags or --input, not both")
    if not args.topic or not args.done:
        raise VaultError("The summary flags need --topic and at least one --done")
    sections = {heading: list(getattr(args, flag)) for flag, heading in SUMMARY_FLAGS if getattr(args, flag)}
    day = {"topic": args.topic, "sections": sections}
    for key, value in (("day", args.day), ("time", args.time and event_time(args.time)), ("open_next", args.open)):
        if value:
            day[key] = value
    return {"reason": args.reason or "Checkpoint: " + args.topic, "days": [day], "operations": []}


def workspace_evidence(agent, model):
    """What an attested checkpoint can measure without a transcript: the agent's claim plus cheap git facts."""
    evidence = {"kind": "attested", "agent": agent, "model": model, "cwd": str(Path.cwd()), "at": now().isoformat()}
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
        if head.returncode == 0:
            status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10)
            evidence["git"] = {"head": head.stdout.strip(),
                               "dirty_files": len([l for l in status.stdout.splitlines() if l.strip()]) if status.returncode == 0 else None}
    except (OSError, subprocess.SubprocessError):
        pass
    return evidence


def attested_checkpoint(vault, args, payload):
    """A checkpoint for an agent with no transcript: the agent names itself and its model, the receipt says it is attested."""
    if not args.model:
        raise VaultError("Without --transcript, pass --model with the verified runtime model id (and --source as the agent id)")
    signer = model_label(args.model)
    agent = args.source or "agent"
    payload = copy.deepcopy(payload)
    stamp = now()
    today = stamp.date().isoformat()
    for entry in payload.get("days", []):
        entry.setdefault("day", today)
    # A retry of the same flags must find the same receipt, so the id binds the
    # agent's content and day, never the clock time or a generated session.
    session = args.session or "day-" + (payload["days"][0]["day"] if payload.get("days") else today)
    prepared = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    capture_id = "attested-" + sha((source_key(agent, session) + ":" + prepared).encode())
    for entry in payload.get("days", []):
        entry.setdefault("time", stamp.strftime("%I:%M %p").lstrip("0"))
    proposal = {"disposition": payload.get("disposition", "captured"), "reason": payload.get("reason", "Attested checkpoint"),
                "evidence": payload.get("evidence") or [workspace_evidence(agent, args.model)],
                "days": payload.get("days", []), "operations": payload.get("operations", []), "anchors": payload.get("anchors", [])}
    receipt = next((r for r in verified_receipts(vault, agent, session) if r["id"] == capture_id), None)
    if receipt is None:
        receipt = apply_proposal(vault, proposal, signer, [], agent, session, capture_id, tier="attested", model_source="self-report")
    live = vault.state / "live" / (source_key(agent, session) + ".json")
    try:
        transcript_ack = live.exists() and json.loads(read_text(live)).get("through") is not None
    except (OSError, ValueError):
        transcript_ack = False
    # A claim never replaces the Stop gate's transcript-bound acknowledgment.
    if not transcript_ack:
        atomic_json(live, {"turn_key": capture_id, "receipt_id": receipt["id"], "status": receipt["disposition"],
                           "completed_at": now().isoformat(), "through": None})
    return receipt


CONTRACT = "10 - Resources/Vault Workflow Contract.md"


def contract_sections(vault, names):
    """The vault's own Contract, one `## ` section at a time; with no names, the section list with line ranges."""
    text = read_text(vault.path(CONTRACT))
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("## ")]
    sections = {lines[s][3:].strip(): (s, (starts[k + 1] if k + 1 < len(starts) else len(lines))) for k, s in enumerate(starts)}
    if not names:
        return "Contract sections (vaultctl.py help write \"<section>\"):\n" + "\n".join(
            f"- {name} (lines {a + 1}-{b})" for name, (a, b) in sections.items())
    chosen = []
    for name in names:
        match = next((key for key in sections if key.lower() == name.strip().lower()), None)
        if match is None:
            raise VaultError(f"No Contract section {name!r}; sections: " + ", ".join(sections))
        a, b = sections[match]
        chosen.append("\n".join(lines[a:b]).rstrip())
    return "\n\n".join(chosen)


class HookResult(tuple):
    """(exit code, stdout, stderr) printed verbatim, in the agent's hook dialect."""


def hook_mode(vault, agent, event):
    try:
        import vault_adapters
        import vault_gate
        config = {}
        try:
            config = json.loads(read_text(Path.home() / ".agent-brain/config.json"))
        except (OSError, RuntimeError, ValueError):
            pass
        adapter = vault_adapters.load()[agent]
        return HookResult(vault_gate.hook(agent, event, json.loads(sys.stdin.read() or "{}"), adapter, vault, config))
    except Exception as exc:  # a hook never blocks or continues a session on an internal error
        try:
            append_jsonl(DEFAULT_AUTOMATION / "hook-errors.jsonl", {"at": now().isoformat(), "hook": f"{agent} {event}", "error": str(exc)[:800]}, vault.state)
        except Exception:
            pass
        return HookResult((0, "", ""))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", default=str(DEFAULT_VAULT))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--backups", default=str(DEFAULT_BACKUPS))
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("paths", nargs="+")
    inspect.add_argument("--hash", action="store_true", help="Return path, sha256 and size only; read the note natively after this")
    daily = sub.add_parser("daily-context", help="Daily navigation without session bodies")
    daily.add_argument("path")
    formatting = sub.add_parser("format-times", help="Preview readable timestamps while preserving original times/authors")
    formatting.add_argument("--apply", action="store_true")
    commit = sub.add_parser("commit")
    commit.add_argument("--input")
    commit.add_argument("--model", required=True, help="Verified runtime model id, not client name")
    commit.add_argument("--reason", required=True)
    check = sub.add_parser("validate")
    check.add_argument("paths", nargs="*")
    check.add_argument("--hook", metavar="AGENT", help="Post-tool hook mode: read the agent's payload on stdin, validate the notes it wrote, log the write; fails open")
    gate = sub.add_parser("gate", help="Stop hook mode: read the agent's payload on stdin and request a checkpoint for an unrecorded delta; fails open")
    gate.add_argument("--agent", required=True)
    maintenance = sub.add_parser("hygiene", help="Records state-v2/hygiene-latest.json and an outcomes row even without --fix; only --fix edits notes")
    maintenance.add_argument("--fix", action="store_true")
    maintenance.add_argument("--no-parity", action="store_true")
    evaluation = sub.add_parser("recall-eval", help="Measure retrieval against the Recall Eval note; no index")
    evaluation.add_argument("--top", type=int, default=5)
    evaluation.add_argument("--record", action="store_true", help="Append the result to the Inbox retrieval audit")
    consolidate = sub.add_parser("consolidate-context", help="Read-only digest of recent sessions to consolidate")
    consolidate.add_argument("--days", type=int, help="Window in days; default: since the last mark, else 7 days")
    consolidate.add_argument("--since")
    consolidate.add_argument("--note", help="Only sessions whose heading names this note or whose Notes Touched links it")
    consolidate.add_argument("--mark", help="Record consolidation through this day, after the updates are written")
    freshness = sub.add_parser("fact-freshness", help="Stale (as of <date>) facts; read-only")
    sub.add_parser("session-brief", help="Plain-text startup continuity: Open line, last sessions, Active Now, recent hook errors; read-only")
    freshness.add_argument("--max-age-days", type=int, default=90)
    links = sub.add_parser("links", help="Read-only wikilink audit: missing targets, ambiguous names, unmatched headings/blocks, orphan candidates")
    links.add_argument("--full", action="store_true", help="Every finding, not the first 20 per kind")
    helper = sub.add_parser("help", help="`help write [section ...]`: list the Contract's sections, or print the named ones")
    helper.add_argument("topic", choices=("write",))
    helper.add_argument("sections", nargs="*")
    context = sub.add_parser("checkpoint-context", help="Event days and times of the current transcript turn")
    context.add_argument("--source", choices=("claude", "codex"), required=True)
    context.add_argument("--session", required=True)
    context.add_argument("--transcript", required=True)
    command = sub.add_parser("checkpoint", help="Append a verified daily session: from a transcript (claude, codex) or attested by any agent")
    command.add_argument("--source", "--agent", dest="source", help="Agent id: claude or codex with --transcript; any lowercase id otherwise")
    command.add_argument("--session", help="Client session id; generated when omitted without a transcript")
    command.add_argument("--transcript", help="Transcript path; binds the receipt to source evidence and verifies the model")
    command.add_argument("--model", help="Verified runtime model id; required without --transcript")
    command.add_argument("--input", help="JSON file; default reads stdin (pipe a file under Windows PowerShell 5.1)")
    command.add_argument("--trivial", metavar="REASON", help="Record a reasoned trivial disposition without JSON input")
    command.add_argument("--summary", action="store_true", help="Print compact verified receipt; retain full receipt on disk")
    command.add_argument("--topic", help="Summary flags instead of JSON: the session topic")
    for flag, heading in SUMMARY_FLAGS:
        command.add_argument("--" + flag, action="append", metavar="TEXT", help=f"One bullet under {heading}; repeatable")
    command.add_argument("--open", help="Replace the day's Open for tomorrow line")
    command.add_argument("--day", help="Event day YYYY-MM-DD; default today, or the transcript's day")
    command.add_argument("--time", help="Event time like 3:42 PM or 15:42; default now, or the transcript's last event")
    command.add_argument("--reason", help="Why this checkpoint exists; default from --topic")
    restore = sub.add_parser("restore")
    restore.add_argument("snapshot")
    restore.add_argument("path")
    restore.add_argument("--expected-sha256", required=True)
    error = sub.add_parser("report-error")
    error.add_argument("--kind", required=True)
    error.add_argument("--error", required=True)
    sub.add_parser("snapshot-runtime")
    args = parser.parse_args(argv)
    vault = Vault(args.vault, args.state, args.backups)
    if args.command == "inspect":
        if args.hash:
            return [{"path": info["path"], "sha256": info["sha256"],
                     "bytes": None if info["text"] is None else len(info["text"].encode("utf-8"))}
                    for info in (vault.inspect(path) for path in args.paths)]
        return [vault.inspect(path) for path in args.paths]
    if args.command == "daily-context":
        return daily_context(vault, args.path)
    if args.command == "format-times":
        return format_times(vault, apply=args.apply)
    if args.command == "commit":
        payload = load_input(args.input)
        return vault.commit(payload["operations"], model_label(args.model), args.reason, payload.get("transaction_id"))
    if args.command == "gate" or (args.command == "validate" and args.hook):
        return hook_mode(vault, args.agent if args.command == "gate" else args.hook, "Stop" if args.command == "gate" else "PostToolUse")
    if args.command == "validate":
        paths = [vault.path(path) for path in args.paths] if args.paths else vault.notes()
        issues = [{"path": str(path), "problems": validate(read_text(path), path)} for path in paths]
        return {"outcome": "invalid" if any(row["problems"] for row in issues) else "valid", "notes": len(paths),
                "issues": [row for row in issues if row["problems"]]}
    if args.command == "hygiene":
        with file_lock(vault.state / "locks" / "scheduled.lock", timeout=1):
            return hygiene(vault, fix=args.fix, check_parity=not args.no_parity)
    if args.command == "recall-eval":
        return recall_eval(vault, top_k=args.top, record=args.record)
    if args.command == "consolidate-context":
        if args.mark:
            return mark_consolidated(vault, args.mark)
        return consolidate_context(vault, days=args.days, since=args.since, note=args.note)
    if args.command == "fact-freshness":
        return fact_freshness(vault, max_age_days=args.max_age_days)
    if args.command == "session-brief":
        return session_brief(vault, DEFAULT_AUTOMATION)
    if args.command == "links":
        from vault_links import audit
        return audit(vault, full=args.full)
    if args.command == "help":
        return contract_sections(vault, args.sections)
    if args.command == "checkpoint-context":
        units = live_units(args)
        return {"source": args.source, "session_id": args.session, "turn_key": units[-1]["turn_key"],
                "model": next((u["model"] for u in reversed(units) if u.get("model")), None),
                "days": sorted({u["day"] for u in units}), "latest_event": {k: units[-1][k] for k in ("day", "time", "end")},
                "day_times": day_times(units), "units": len(units), "first_evidence": default_evidence(units)[0]}
    if args.command == "checkpoint":
        flagged = args.topic is not None or any(getattr(args, flag) for flag, _ in SUMMARY_FLAGS)
        if args.trivial is not None:
            if not args.trivial.strip():
                raise VaultError("--trivial needs a reason")
            refuse_trivial(vault, args)
            payload = {"disposition": "trivial", "reason": args.trivial.strip()}
        elif flagged:
            payload = flags_payload(args)
        else:
            payload = load_input(args.input)
        if args.transcript:
            if not args.source or not args.session:
                raise VaultError("--transcript needs --source claude|codex and --session")
            receipt = checkpoint(vault, args, payload)
        else:
            receipt = attested_checkpoint(vault, args, payload)
        return receipt_summary(receipt) if args.summary else receipt
    if args.command == "restore":
        return vault.restore(args.snapshot, args.path, args.expected_sha256)
    if args.command == "report-error":
        result = {"at": now().isoformat(), "kind": args.kind, "outcome": "failed", "error": args.error[:800],
                  "model": None, "usage": None, "cost_usd": None}
        append_jsonl(vault.state / "outcomes.jsonl", result, vault.state)
        return result
    if args.command == "snapshot-runtime":
        try:
            from vault_runtime import write_baseline
        except ImportError:
            raise VaultError("The runtime baseline is optional: copy contrib/windows-audit/ into the controller folder first")
        return write_baseline()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    try:
        result = main()
        if isinstance(result, HookResult):
            code, out, err = result
            sys.stdout.write(out + ("\n" if out and not out.endswith("\n") else ""))
            sys.stderr.write(err)
            sys.exit(code)
        print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        sys.exit(2 if isinstance(result, dict) and result.get("outcome") in ("invalid", "needs_review") else 0)
    except Exception as exc:
        print(json.dumps({"outcome": "failed", "error": str(exc)}))
        sys.exit(1)
