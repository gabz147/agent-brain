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
    attested = not units  # no transcript: the agent attests, and the receipt says so
    source = {u["id"]: u for u in units}
    for evidence in proposal["evidence"]:
        if attested:
            if not isinstance(evidence, dict) or evidence.get("kind") != "attested" or not evidence.get("agent"):
                raise VaultError("An attested checkpoint needs attested evidence naming the agent")
            continue
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
        valid = ", ".join(sorted(source_days))
        seen = set()
        for day in days:
            if not day.get("day"):
                raise VaultError(f"This turn spans {valid}; give each days entry its day" if not attested else "Give each days entry its day")
            if attested:
                try:
                    dt.date.fromisoformat(str(day["day"]))
                except ValueError:
                    raise VaultError("An attested day must be YYYY-MM-DD")
            if (not attested and day["day"] not in source_days) or day["day"] in seen:
                raise VaultError(f"Daily capture must use distinct source-local dates; valid days: {valid}")
            seen.add(day["day"])
            try:
                dt.datetime.strptime(day.get("time", ""), "%I:%M %p")
            except ValueError:
                raise VaultError(f"Session time for {day['day']} must look like 3:42 PM, or be omitted to use that day's last event")
            if not attested:
                times = [u["time"] for u in units if u["day"] == day["day"]]
                if day["time"] not in times:
                    raise VaultError(f"Session time {day['time']} is not a source event on {day['day']} (first {times[0]}, last {times[-1]}); omit it to use the last")
            if not day.get("sections", {}).get("What Got Done"):
                raise VaultError("Capture needs an outcome")
        if not attested and seen != source_days:
            missing = ", ".join(sorted(source_days - seen))
            raise VaultError(f"Capture must account for every source-local day in this batch; add a days entry for {missing}")
        for op in proposal.get("operations", []):
            path = vault.path(op["path"])
            if is_daily(path):
                raise VaultError("Daily notes must use the structured days field")
            if path.name == "VAULT-INDEX.md" or (path.name == "Decisions.md" and "content" in op):
                raise VaultError("VAULT-INDEX changes or whole-note Decisions rewrites need a separate vaultctl commit")
            if path.name == "Decisions.md":
                for edit in op.get("edits", []):
                    check_decision_edit(edit)


def check_decision_edit(edit):
    """Inside checkpoints a Decisions edit may only change a non-locked row's Enforced in/Status cells."""
    old, new = edit.get("old", ""), edit.get("new", "")
    if not (old.startswith("| ") and new.startswith("| ")) or "\n" in old or "\n" in new:
        raise VaultError("A Decisions edit must replace exactly one table row")
    old_cells, new_cells = old.strip().strip("|").split("|"), new.strip().strip("|").split("|")
    if len(old_cells) != len(new_cells) or old_cells[:-2] != new_cells[:-2]:
        raise VaultError("A Decisions edit may change only the Enforced in and Status cells; original wording stays")
    if old_cells[-1].strip().startswith("locked"):
        raise VaultError("Superseding a locked decision needs the owner's words and an interactive vaultctl commit")


def apply_proposal(vault, proposal, signer, units, provider, session_id, capture_id, transaction_id=None,
                   tier="transcript", model_source="transcript"):
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
               "tier": tier, "model_source": model_source,
               "disposition": proposal["disposition"], "reason": proposal["reason"], "evidence": proposal["evidence"],
               "units": [u["id"] for u in units], "ranges": [{k: u[k] for k in ("start", "end", "line_sha256", "fragment", "fragments")} for u in units],
               "anchors": anchors, "writer_model": signer, "transaction_id": (result or {}).get("transaction_id")}
    record_receipt(vault, provider, session_id, receipt)
    if not any(r["id"] == capture_id for r in verified_receipts(vault, provider, session_id)):
        raise VaultError("Receipt read-back verification failed")
    append_jsonl(vault.state / "outcomes.jsonl", {"id": capture_id, "at": now().isoformat(), "kind": "commit",
                 "outcome": proposal["disposition"], "model": signer, "units": len(units)}, vault.state)
    return receipt
