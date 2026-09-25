"""Validated checkpoint commits and durable capture receipts.

Checkpoints are written live by the agent in its own session. There is no
background or scheduled model capture: nothing here starts a model call.
"""
from __future__ import annotations

import datetime as dt
import copy
import re

from vault_core import VaultError, append_jsonl, daily_operation, is_daily, now, sha
from vault_sources import anchor_valid, record_receipt, verified_receipts


def validate_proposal(vault, proposal, units):
    disposition = proposal.get("disposition")
    if disposition not in ("captured", "already_covered", "trivial", "blocked"):
        raise VaultError("Unknown disposition")
    if disposition == "blocked":
        raise VaultError("Capture blocked: " + proposal.get("reason", "unspecified"))
    if not proposal.get("reason") or not proposal.get("evidence"):
        raise VaultError("Disposition needs a reason and source evidence")
    source = {u["id"]: u for u in units}
    for evidence in proposal["evidence"]:
        unit = source.get(evidence.get("unit_id"))
        quote = evidence.get("quote")
        if not unit or not isinstance(quote, str) or len(quote.strip()) < 8 or quote not in unit["text"]:
            raise VaultError("Claimed source evidence does not match")
    if disposition != "captured" and (proposal.get("days") or proposal.get("operations")):
        raise VaultError("Non-capture disposition cannot perform writes")
    if disposition == "already_covered":
        if not proposal.get("anchors"):
            raise VaultError("Already-covered requires daily-section anchors")
        for anchor in proposal["anchors"]:
            fragment = anchor.get("text", "")
            anchor["sha256"] = sha(fragment.encode())
            if not fragment.startswith("## Session") or len(fragment) < 120 or not anchor_valid(vault, anchor):
                raise VaultError("Existing daily coverage anchor is invalid")
    if disposition == "captured":
        days = proposal.get("days", [])
        if not days:
            raise VaultError("Capture requires a daily checkpoint")
        source_days = {u["day"] for u in units}
        seen = set()
        for day in days:
            if day["day"] not in source_days or day["day"] in seen:
                raise VaultError("Daily capture must use distinct source-local dates")
            seen.add(day["day"])
            dt.datetime.strptime(day["time"], "%I:%M %p")
            if not any(u["day"] == day["day"] and u["time"] == day["time"] for u in units):
                raise VaultError("Session time must come from source evidence")
            if not day.get("sections", {}).get("What Got Done"):
                raise VaultError("Capture needs an outcome")
        if seen != source_days:
            raise VaultError("Capture must account for every source-local day in this batch")
        for op in proposal.get("operations", []):
            path = vault.path(op["path"])
            if is_daily(path):
                raise VaultError("Daily notes must use the structured days field")
            if path.name in ("VAULT-INDEX.md", "Decisions.md"):
                # Structured checkpoints can append decisions but cannot rewrite
                # profile, protected boot rules or prior decision text.
                if path.name == "VAULT-INDEX.md" or "content" in op or op.get("edits"):
                    raise VaultError("Protected note requires an interactive reconciliation")


def apply_proposal(vault, proposal, signer, units, provider, session_id, capture_id, transaction_id=None):
    validate_proposal(vault, proposal, units)
    marker = "<!-- vault-capture:" + capture_id + " -->"
    operations = copy.deepcopy(proposal.get("operations", []))
    for operation in operations:
        for edit in operation.get("edits", []):
            edit["new"] = edit["new"].replace("`(unknown-model)`", f"`({signer})`")
        if operation.get("append"):
            operation["append"] = operation["append"].replace("`(unknown-model)`", f"`({signer})`")
        if "content" in operation:
            old_lines = set((vault.inspect(operation["path"])["text"] or "").splitlines())
            operation["content"] = "".join(line if line.rstrip("\r\n") in old_lines else line.replace("`(unknown-model)`", f"`({signer})`") for line in operation["content"].splitlines(keepends=True))
    daily_paths = []
    for day in proposal.get("days", []):
        op = daily_operation(vault, day["day"], day["time"], day["topic"], day["sections"], signer, marker, day.get("open_next"))
        if op:
            operations.append(op)
            daily_paths.append(op["path"])
        else:
            from vault_core import daily_path
            daily_paths.append(daily_path(day["day"]))
    result = None
    if proposal["disposition"] == "captured":
        transaction_id = transaction_id or capture_id
        manifest = vault.backups / transaction_id / "manifest.json"
        if operations or manifest.exists():
            result = vault.commit(operations or [{"path": daily_paths[0]}], signer, "Capture " + provider + "/" + session_id, transaction_id)
        anchors = []
        for path in daily_paths:
            text = vault.inspect(path)["text"] or ""
            blocks = re.split(r"(?=^## Session\b)", text, flags=re.M)
            block = next((part for part in blocks if marker in part), None)
            if not block:
                raise VaultError("Committed daily marker could not be verified")
            # Later appends may add trailing whitespace to the previous block.
            block = block.rstrip()
            anchors.append({"path": path, "text": block, "sha256": sha(block.encode())})
    else:
        anchors = proposal.get("anchors", [])
    receipt = {"id": capture_id, "at": now().isoformat(), "provider": provider, "session_id": session_id,
               "disposition": proposal["disposition"], "reason": proposal["reason"], "evidence": proposal["evidence"],
               "units": [u["id"] for u in units], "ranges": [{k: u[k] for k in ("start", "end", "line_sha256", "fragment", "fragments")} for u in units],
               "anchors": anchors, "writer_model": signer, "transaction_id": (result or {}).get("transaction_id")}
    record_receipt(vault, provider, session_id, receipt)
    if not any(r["id"] == capture_id for r in verified_receipts(vault, provider, session_id)):
        raise VaultError("Receipt read-back verification failed")
    append_jsonl(vault.state / "outcomes.jsonl", {"id": capture_id, "at": now().isoformat(), "kind": "commit",
                 "outcome": proposal["disposition"], "model": signer, "units": len(units)}, vault.state)
    return receipt
