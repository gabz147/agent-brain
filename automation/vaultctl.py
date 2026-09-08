"""Single entry point for both agents and unattended vault workflows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from vault_core import (DEFAULT_AUTOMATION, DEFAULT_BACKUPS, DEFAULT_STATE, DEFAULT_VAULT, HERE, Conflict, Vault, VaultError,
                        append_jsonl, atomic_json, file_lock, model_label, now, read_text, sha, validate)
from vault_sources import source_key, stream_units, uncovered, verified_receipts
from vault_capture import Deferred, apply_proposal, capture
from vault_hygiene import hygiene
from vault_queue import discover_codex, drain, enqueue


def load_input(path):
    return json.loads(read_text(path) if path else sys.stdin.read())


def live_units(args):
    units = list(stream_units(args.transcript, args.source, args.session))
    if not units:
        raise VaultError("No transcript evidence")
    turn = units[-1].get("turn_key")
    if not turn:
        raise VaultError("No human-origin turn boundary")
    return [u for u in units if u.get("turn_key") == turn]


def checkpoint(vault, args, payload):
    units = live_units(args)
    signer = model_label(next((u["model"] for u in reversed(units) if u.get("model")), None))
    # Verification tool output grows the transcript between retries. Bind the
    # same prepared checkpoint to its human turn and payload, not that tail.
    prepared = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    capture_id = "live-" + sha((source_key(args.source, args.session) + ":" + units[0]["id"] + ":" + prepared).encode())
    proposal = {"disposition": payload.get("disposition", "captured"), "reason": payload.get("reason", "Interactive checkpoint"),
                "evidence": payload.get("evidence") or [{"unit_id": units[0]["id"], "quote": units[0]["text"][:120]}],
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", default=str(DEFAULT_VAULT))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--backups", default=str(DEFAULT_BACKUPS))
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("paths", nargs="+")
    commit = sub.add_parser("commit")
    commit.add_argument("--input")
    commit.add_argument("--model", required=True, help="Verified runtime model id, not client name")
    commit.add_argument("--reason", required=True)
    check = sub.add_parser("validate")
    check.add_argument("paths", nargs="*")
    maintenance = sub.add_parser("hygiene")
    maintenance.add_argument("--fix", action="store_true")
    maintenance.add_argument("--no-parity", action="store_true")
    for name in ("capture", "checkpoint-context", "checkpoint"):
        command = sub.add_parser(name)
        command.add_argument("--source", choices=("claude", "codex"), required=True)
        command.add_argument("--session", required=True)
        command.add_argument("--transcript", required=True)
        if name == "checkpoint":
            command.add_argument("--input")
    queue = sub.add_parser("drain")
    queue.add_argument("--directory", default=str(DEFAULT_AUTOMATION))
    queue.add_argument("--max-attempts", type=int, default=8)
    queue.add_argument("--no-discover", action="store_true")
    discovery = sub.add_parser("discover-codex")
    discovery.add_argument("--directory", default=str(DEFAULT_AUTOMATION))
    enqueue_parser = sub.add_parser("enqueue")
    enqueue_parser.add_argument("--input")
    enqueue_parser.add_argument("--directory", default=str(DEFAULT_AUTOMATION))
    restore = sub.add_parser("restore")
    restore.add_argument("snapshot")
    restore.add_argument("path")
    restore.add_argument("--expected-sha256", required=True)
    error = sub.add_parser("report-error")
    error.add_argument("--kind", required=True)
    error.add_argument("--error", required=True)
    sub.add_parser("costs")
    sub.add_parser("snapshot-runtime")
    args = parser.parse_args(argv)
    vault = Vault(args.vault, args.state, args.backups)
    if args.command == "inspect":
        return [vault.inspect(path) for path in args.paths]
    if args.command == "commit":
        payload = load_input(args.input)
        return vault.commit(payload["operations"], model_label(args.model), args.reason, payload.get("transaction_id"))
    if args.command == "validate":
        paths = [vault.path(path) for path in args.paths] if args.paths else vault.notes()
        issues = [{"path": str(path), "problems": validate(read_text(path), path)} for path in paths]
        return {"outcome": "invalid" if any(row["problems"] for row in issues) else "valid", "notes": len(paths),
                "issues": [row for row in issues if row["problems"]]}
    if args.command == "hygiene":
        with file_lock(vault.state / "locks" / "scheduled.lock", timeout=1):
            return hygiene(vault, fix=args.fix, check_parity=not args.no_parity)
    if args.command == "capture":
        return capture(vault, {"source": args.source, "session_id": args.session, "transcript_path": args.transcript})
    if args.command == "checkpoint-context":
        units = live_units(args)
        return {"source": args.source, "session_id": args.session, "turn_key": units[-1]["turn_key"],
                "model": next((u["model"] for u in reversed(units) if u.get("model")), None),
                "days": sorted({u["day"] for u in units}), "latest_event": {k: units[-1][k] for k in ("day", "time", "end")},
                "units": len(units), "first_evidence": {"unit_id": units[0]["id"], "quote": units[0]["text"][:120]}}
    if args.command == "checkpoint":
        return checkpoint(vault, args, load_input(args.input))
    if args.command == "drain":
        return drain(vault, args.directory, discover=not args.no_discover, max_attempts=args.max_attempts)
    if args.command == "discover-codex":
        return {"enqueued": discover_codex(vault, args.directory)}
    if args.command == "enqueue":
        enqueue(args.directory, load_input(args.input))
        return {"status": "enqueued"}
    if args.command == "restore":
        return vault.restore(args.snapshot, args.path, args.expected_sha256)
    if args.command == "report-error":
        result = {"at": now().isoformat(), "kind": args.kind, "outcome": "failed", "error": args.error[:800],
                  "model": None, "usage": None, "cost_usd": None}
        append_jsonl(vault.state / "outcomes.jsonl", result, vault.state)
        return result
    if args.command == "costs":
        ledger = vault.state / "outcomes.jsonl"
        rows = [json.loads(line) for line in read_text(ledger).splitlines() if line.strip()] if ledger.exists() else []
        attempts = [row for row in rows if row.get("kind") == "capture"]
        reported = [row["cost_usd"] for row in attempts if isinstance(row.get("cost_usd"), (int, float))]
        totals = {key: sum((row.get("usage") or {}).get(key, 0) or 0 for row in attempts)
                  for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")}
        outcomes = {}
        for row in rows:
            key = row.get("kind", "unknown") + ":" + row.get("outcome", "unknown")
            outcomes[key] = outcomes.get(key, 0) + 1
        return {"capture_attempts": len(attempts), "reported_cost_usd": round(sum(reported), 8),
                "attempts_without_cost": len(attempts) - len(reported), "reported_token_totals": totals,
                "attempts_without_usage": sum(row.get("usage") is None for row in attempts),
                "outcomes": outcomes, "cost_basis": "CLI-reported estimate; not a subscription invoice"}
    if args.command == "snapshot-runtime":
        from vault_runtime import write_baseline
        return write_baseline()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
    try:
        result = main()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(2 if isinstance(result, dict) and result.get("outcome") in ("invalid", "needs_review") else 0)
    except Deferred as exc:
        print(json.dumps({"outcome": "deferred", "error": str(exc)}))
        sys.exit(75)
    except Exception as exc:
        print(json.dumps({"outcome": "failed", "error": str(exc)}))
        sys.exit(1)
