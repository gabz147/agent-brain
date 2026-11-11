"""Deterministic vault hygiene. No model invocation and no automatic archiving."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil

from vault_core import (DEFAULT_VAULT, HERE, SCHEMA, VaultError, append_jsonl, atomic_json, file_lock,
                        MONTHS, format_note_time, frontmatter, is_daily, now, parse_note_time, read_text, sha, validate)

FOLDER_PROJECTS = SCHEMA["folder_projects"]
PRIORITY_LINE = 300  # characters an Active Priorities item may take, without its bullet


def schema_block():
    quote = lambda values: ", ".join("`" + value + "`" for value in values)
    return "\n".join([
        "<!-- VAULT SCHEMA START -->",
        "- Required keys: " + quote(SCHEMA["required"]) + ".",
        "- Optional existing key: " + quote(SCHEMA["optional"]) + ". No other keys.",
        "- Status: " + quote(SCHEMA["status"]) + ".",
        ("- Project: " + quote(SCHEMA["project_allowlist"]) + "." if SCHEMA.get("project_allowlist") else
         "- Project: any kebab-case slug; optional project_allowlist in vault-schema.json. Starter values: " + quote(SCHEMA["project"]) + "."),
        "- Type: " + quote(SCHEMA["type"]) + ".",
        "- Signature: lowercase model label/ID, `human`, `automation`, or `unknown-model`; legacy tags remain valid in history.",
        "- Updated: readable local write time, for example `September 23, 2026 at 6:20:14 AM (UTC-06:00)`; legacy ISO timestamps and `YYYY-MM-DD` dates remain valid. The writer uses the system clock and timezone.",
        "<!-- VAULT SCHEMA END -->"
    ])


def missing_metadata(text, path):
    """Repair missing keys only. Invalid/ambiguous values require review."""
    try:
        fields, body = frontmatter(text)
    except VaultError:
        if text.lstrip("\ufeff").startswith("---"):
            return None
        fields, body = {}, text
    if set(fields) - set(SCHEMA["required"] + SCHEMA["optional"]):
        return None
    default_project = FOLDER_PROJECTS.get(path.parts[0][:2], "meta")
    if path.parts[0].startswith(("09", "00")):
        return None  # archive/inbox project cannot reliably be inferred
    inferred_type = "log" if is_daily(path) else "index" if path.stem == path.parent.name else "reference"
    defaults = {"status": "active", "project": default_project, "type": inferred_type,
                "updated_by": "automation", "updated": format_note_time(now().replace(microsecond=0))}
    missing = [k for k in SCHEMA["required"] if k not in fields]
    if not missing:
        return None
    if fields:
        lines = text.splitlines(keepends=True)
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        newline = "\r\n" if "\r\n" in text else "\n"
        return "".join(lines[:end]) + "".join(k + ": " + defaults[k] + newline for k in missing) + "".join(lines[end:])
    return "---\n" + "".join(k + ": " + v + "\n" for k, v in defaults.items()) + "---\n\n" + body


def age_priorities(text, today=None):
    today = today or now().date()
    newline = "\r\n" if "\r\n" in text else "\n"
    chunks = re.split(r"(?=^## )", text, flags=re.M)
    moved = []
    count_active = 0
    for i, chunk in enumerate(chunks):
        heading = chunk.splitlines()[0] if chunk else ""
        if heading not in ("## Active Now", "## Next", "## Waiting"):
            continue
        category = "**Other**"
        keep = []
        for line in chunk.splitlines(keepends=True):
            if re.fullmatch(r"\*\*.+\*\*\s*", line):
                category = line.strip()
            match = re.search(r"`touched: (\d{4}-\d{2}-\d{2})`", line)
            if line.startswith("- ") and match:
                try:
                    stale = (today - dt.date.fromisoformat(match.group(1))).days > 14
                except ValueError:
                    stale = False
                if stale:
                    moved.append((category, line.rstrip("\r\n")))
                    continue
            if heading == "## Active Now" and line.startswith("- "):
                count_active += 1
            keep.append(line)
        chunks[i] = "".join(keep)
    if moved:
        review = next((i for i, chunk in enumerate(chunks) if chunk.startswith("## Review\n") or chunk.startswith("## Review\r\n")), None)
        if review is None:
            raise VaultError("Cannot age priorities without the Review section")
        body = chunks[review].rstrip("\r\n").splitlines()
        for category, line in moved:
            # Merge under an existing Review category heading instead of repeating it.
            heading_at = max((i for i, existing in enumerate(body) if existing.strip() == category), default=None)
            if heading_at is None:
                body += ["", category, line]
                continue
            end = heading_at + 1
            while end < len(body) and body[end].startswith("- "):
                end += 1
            body.insert(end, line)
        chunks[review] = newline.join(body) + newline + newline
    return "".join(chunks), len(moved), count_active


def recent_review(text, today=None):
    """Review items touched within 14 days: misfiled, they belong back in Active Now, Next or Waiting."""
    today = today or now().date()
    review = re.search(r"^## Review\r?\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    found = []
    for line in (review.group(1).splitlines() if review else []):
        match = re.search(r"`touched: (\d{4}-\d{2}-\d{2})`", line)
        if line.startswith("- ") and match:
            try:
                if (today - dt.date.fromisoformat(match.group(1))).days <= 14:
                    found.append(line[:80])
            except ValueError:
                pass
    return found


def parity(home):
    """Each installed agent's block and skill copies against one canonical rendering: O(agents), any number of them."""
    import vault_adapters as adapters_module
    home = Path(home)
    try:
        adapters = adapters_module.load()
        body = adapters_module.block_body()
    except (adapters_module.AdapterError, OSError) as exc:
        return [str(exc)]
    # An agent participates when its block is installed; a single-agent
    # installation checks only its own copies without demanding another agent.
    installed = [a for a in adapters.values() if adapters_module.is_installed(a, home, adapters)]
    if not installed:
        return ["No installed client boot files"]
    issues, reference, mismatched = [], {}, set()
    for adapter in installed:
        dirs = [adapters_module.expand(d, home) for d in adapter["skills"] + adapter.get("legacy_skills", [])]
        for skill in adapters_module.SKILLS:
            copies = [d / skill / "SKILL.md" for d in dirs if (d / skill / "SKILL.md").is_file()]
            if not copies:
                issues.append(f"Missing installed skill: {skill} for {adapter['id']}")
            for path in copies:
                if reference.setdefault(skill, path.read_bytes()) != path.read_bytes() and skill not in mismatched:
                    mismatched.add(skill)
                    issues.append("Skill mirror mismatch: " + skill)
        block = adapters_module.installed_block(adapter, home)
        if block is None:
            issues.append("Missing shared-rule block: " + str(adapters_module.instructions_path(adapter, home)))
        elif block.replace("\r\n", "\n") != adapters_module.render_block(adapter, body):
            issues.append(f"Boot shared-rule block differs from this release: {adapter['id']}")
    return issues


def idle_hooks(vault, home):
    """Agents whose Brain hooks are installed but have never started a session, usually because the client still waits for a trust step."""
    import vault_adapters as adapters_module
    try:
        seen = json.loads(read_text(vault.state / "hooks-seen.json"))
    except (OSError, ValueError):
        seen = {}
    idle = []
    for adapter in adapters_module.load().values():
        hooks = adapter.get("hooks")
        if not hooks or adapter["id"] in seen:
            continue
        config = adapters_module.expand(hooks["path"], home)
        try:
            wired = config.is_file() and "agent-hook.py" in config.read_text(encoding="utf-8-sig")
        except OSError:
            wired = False
        if wired:
            idle.append(adapter["id"])
    return idle


def snapshot_rows(vault):
    """One row per transaction folder: id, time, status, the notes it touched and its size on disk."""
    rows = []
    if not vault.backups.is_dir():
        return rows
    for entry in os.scandir(vault.backups):
        if not entry.is_dir() or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", entry.name):
            continue
        size, newest = 0, 0.0
        for item in os.scandir(entry.path):
            try:
                stat = item.stat()
            except OSError:
                continue
            size += stat.st_size
            newest = max(newest, stat.st_mtime)
        try:
            manifest = json.loads(read_text(Path(entry.path) / "manifest.json"))
        except (OSError, ValueError):
            manifest = {}
        try:
            at = dt.datetime.fromisoformat(manifest["time"]).timestamp()
        except (KeyError, TypeError, ValueError):
            at = newest
        rows.append({"id": entry.name, "path": Path(entry.path), "at": at, "bytes": size, "status": manifest.get("status") or "no-manifest",
                     "notes": [item["path"] for item in manifest.get("files", []) if isinstance(item, dict) and "path" in item]})
    return sorted(rows, key=lambda row: row["at"])


def snapshots(vault, prune=False, keep_days=30, apply=False):
    """Snapshot inventory, and with prune the transactions safe to drop.

    Kept whatever their age: unfinished transactions, and for every note the newest transaction that
    touched it, so each note always has one recovery point. Notes themselves are never touched."""
    rows = snapshot_rows(vault)
    report = {"outcome": "report", "transactions": len(rows), "megabytes": round(sum(r["bytes"] for r in rows) / 1e6, 1),
              "oldest": dt.datetime.fromtimestamp(rows[0]["at"]).date().isoformat() if rows else None,
              "unfinished": [r["id"] for r in rows if r["status"] in ("interrupted", "prepared")]}
    if not prune:
        return report
    if keep_days < 1:
        raise VaultError("--keep-days must be at least 1")
    cutoff = now().timestamp() - keep_days * 86400
    newest_for_note = {}
    for row in rows:
        if row["status"] == "committed":
            for note in row["notes"]:
                newest_for_note[note] = row["id"]
    protected = set(newest_for_note.values())
    removable = [r for r in rows if r["at"] < cutoff and r["id"] not in protected and r["status"] not in ("interrupted", "prepared")]
    report.update(outcome="pruned" if apply else "preview", keep_days=keep_days, removable=len(removable),
                  removable_megabytes=round(sum(r["bytes"] for r in removable) / 1e6, 1),
                  kept_as_newest_for_a_note=len(protected))
    if apply:
        with file_lock(vault.state / "locks" / "commits.lock"):
            for row in removable:
                if row["path"].parent == vault.backups:
                    shutil.rmtree(row["path"], ignore_errors=True)
        report["remaining"] = len(snapshot_rows(vault))
        append_jsonl(vault.state / "outcomes.jsonl", {"at": now().isoformat(), "kind": "snapshots", "outcome": "pruned",
                     "removed": len(removable), "megabytes": report["removable_megabytes"], "keep_days": keep_days}, vault.state)
    return report


def daily_structure(text, path=None):
    issues = []
    _, body = frontmatter(text)
    for pattern, problem in [(r"^# \w+, \w+ \d{1,2}, \d{4}\r?$", "Missing human-readable date heading"),
                             (r"^\*\*Open for tomorrow:\*\*[^\r\n]*", "Missing Open for tomorrow line")]:
        # The Open-line contract was introduced September 3. Do not rewrite
        # older immutable history to retrofit a later template convention.
        legacy = path is not None and is_daily(path) and Path(path).stem < "2026-09-03"
        if problem == "Missing Open for tomorrow line" and legacy:
            continue
        if not re.search(pattern, body, re.M):
            issues.append(problem)
    return issues


def _section(text, heading):
    match = re.search(r"^## " + re.escape(heading) + r"[ \t]*\r?\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return match.group(1) if match else ""


def _marker_time(value):
    """Naive local wall-clock time from ISO (`2026-10-20T22:40`, space form, date only) or the readable note format."""
    value = value.strip()
    try:
        parsed = parse_note_time(value)
        return parsed.replace(tzinfo=None)
    except ValueError:
        pass
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?))?", value)
    if match:
        day, clock = match.groups()
        return dt.datetime.fromisoformat(day + "T" + clock) if clock else _day_end(day)
    match = re.fullmatch(r"([A-Za-z]+) (\d{1,2}), (\d{4}) at (\d{1,2}):(\d{2}) ?([AP]M)", value)
    if match and match.group(1) in MONTHS:
        month, day, year, hour, minute, period = match.groups()
        return dt.datetime(int(year), MONTHS.index(month) + 1, int(day), int(hour) % 12 + (12 if period == "PM" else 0), int(minute))
    raise ValueError("Unrecognized timestamp: " + value)


def _day_end(day):
    return dt.datetime.fromisoformat(day + "T23:59:59")


def profile_drift(vault):
    """Read-only check that the Who I Am profile covers recent Profile Updates and the active projects."""
    info = vault.inspect("VAULT-INDEX.md")
    text = info["text"] or ""
    who = _section(text, "Who I Am")
    marker = re.search(r"Profile reviewed through:\s*(.+?)\s*$", _section(text, "Living Profile"), re.M)
    baseline = None
    if marker:
        marker = marker.group(1).strip().strip("*_`").strip()
        try:
            baseline = _marker_time(marker)
        except ValueError:
            pass
    if baseline is None:
        marker = None
        try:
            baseline = _marker_time(frontmatter(text)[0]["updated"])
        except (VaultError, KeyError, ValueError):
            baseline = dt.datetime.min
    pending = []
    for path in vault.notes():
        if not is_daily(path) or path.stem < baseline.date().isoformat():
            continue
        rel = path.relative_to(vault.root).as_posix()
        lines = read_text(path).splitlines()
        session, session_at, in_updates = None, None, False
        for number, line in enumerate(lines, 1):
            if line.startswith("## "):
                in_updates = False
                session = line[3:].strip() if re.match(r"## Session \d+\b", line) else None
                at = re.search(r"[—-]\s*(\d{1,2}):(\d{2}) ?([AP]M)\b", line)
                session_at = _day_end(path.stem)
                if at:
                    hour, minute, period = at.groups()
                    session_at = dt.datetime.fromisoformat(path.stem + "T00:00:00").replace(
                        hour=int(hour) % 12 + (12 if period == "PM" else 0), minute=int(minute))
            elif line.startswith("#"):
                in_updates = session is not None and line.strip() == "### Profile Updates"
            elif in_updates and line.lstrip().startswith("-"):
                item = line.lstrip()[1:].strip()
                if item and not item.lower().startswith("none") and session_at > baseline:
                    pending.append({"date": path.stem, "path": rel, "line": number, "session": session, "text": item})
    missing = []
    stems = {}
    for path in vault.notes():
        stems.setdefault(path.stem, path)
    priorities = vault.inspect("Active Priorities.md")["text"] or ""
    lowered = who.lower()
    for section in ("Active Now", "Next"):
        for line in _section(priorities, section).splitlines():
            if not line.startswith("- "):
                continue
            for target in dict.fromkeys(t.strip() for t in re.findall(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", line)):
                note = stems.get(target)
                if note is None or target == "Machine Inventory" or any(m["name"] == target for m in missing):
                    continue
                try:
                    fields = frontmatter(read_text(note))[0]
                except VaultError:
                    fields = {}
                if fields.get("project") == "meta":
                    continue
                if not any(name.lower() in lowered for name in [target] + list(fields.get("aliases", []))):
                    missing.append({"name": target, "section": section})
    return {"outcome": "passed" if not pending and not missing else "needs_review", "marker": marker,
            "baseline": baseline.isoformat(), "pending_profile_updates": pending, "missing_from_profile": missing}


def hygiene(vault, fix=False, check_parity=True, home=None):
    """Fully scan every live note and return a signed machine-readable report."""
    report = {"version": 2, "at": now().isoformat(), "writer": "automation", "notes": 0,
              "issues": [], "repairs": [], "aged": 0, "cost_usd": 0, "model_calls": 0}
    operations = {}
    notes = vault.notes()
    texts, rels = {}, {}
    for path in notes:
        info = vault.inspect(path)
        rel, text = info["path"], info["text"]
        texts[rel] = text
        rels[path] = rel
        report["notes"] += 1
        problems = validate(text, path)
        if problems and fix:
            repaired = missing_metadata(text, Path(rel))
            if repaired is not None and not validate(repaired, path) and not is_daily(path):
                operations[rel] = {"path": rel, "expected_sha256": info["sha256"], "content": repaired}
                texts[rel] = repaired
                report["repairs"].append("Added missing metadata: " + rel)
                problems = []
        if not problems and is_daily(path):
            problems = daily_structure(text, path)
        report["issues"].extend({"path": rel, "problem": problem} for problem in problems)
    # Contracted folder indexes, including recursively held notes.
    for folder in sorted(vault.root.iterdir()):
        if not folder.is_dir() or folder.name[:2] not in SCHEMA["index_folders"]:
            continue
        index_path = folder / (folder.name + ".md")
        info = vault.inspect(index_path)
        rel, text = info["path"], texts.get(info["path"], "")
        if not text:
            report["issues"].append({"path": rel, "problem": "Missing required folder index"})
            continue
        revised = text
        links = lambda body, stem: re.search(r"\[\[" + re.escape(stem) + r"(?:[|#][^\]]*)?\]\]", body)
        members = [p for p in notes if folder in p.parents and p != index_path]
        # A subfolder index (<dir>/<dir>.md) reachable from the folder index covers the notes it links.
        covering, frontier = [text], [text]
        sub_indexes = {p for p in members if p.stem == p.parent.name and p.parent != folder}
        while frontier:
            body = frontier.pop()
            for sub in [p for p in sub_indexes if links(body, p.stem)]:
                sub_indexes.discard(sub)
                covering.append(texts.get(rels[sub], ""))
                frontier.append(covering[-1])
        for note in members:
            if any(links(body, note.stem) for body in covering[1:]):
                continue
            if not links(revised, note.stem):
                if fix:
                    revised = revised.rstrip() + f"\n- [[{note.stem}]] — Reference for {note.stem}. `(automation)`\n"
                    report["repairs"].append("Added index member: " + note.stem)
                else:
                    report["issues"].append({"path": rel, "problem": "Unindexed note: " + note.stem})
        for line in revised.splitlines():
            if line.startswith("- ") and "[[" in line and not re.search(r"`\([a-z0-9][a-z0-9 ._-]*\)`\s*$", line):
                if fix:
                    revised = revised.replace(line, line.rstrip() + " `(unknown-model)`", 1)
                    report["repairs"].append("Marked unknown historical index author: " + rel)
                else:
                    report["issues"].append({"path": rel, "problem": "Index entry lacks an author tag"})
        if revised != text:
            operations[rel] = {"path": rel, "expected_sha256": info["sha256"], "content": revised}
    priority = "Active Priorities.md"
    if priority in texts:
        revised, aged, count_active = age_priorities(texts[priority])
        misfiled = recent_review(texts[priority])
        if misfiled:
            report["recent_review"] = misfiled  # informational; does not block the stamp
        long_items = [line[:60] for line in texts[priority].splitlines() if line.startswith("- ") and len(line) > PRIORITY_LINE + 2]
        if long_items:
            report["long_priorities"] = long_items  # informational: the Contract caps an item at 300 characters
        if count_active > 5:
            report["issues"].append({"path": priority, "problem": "Active Now exceeds five committed items"})
        if aged:
            if fix:
                info = vault.inspect(priority)
                operations[priority] = {"path": priority, "expected_sha256": info["sha256"], "content": revised}
                report["aged"] = aged
            else:
                report["issues"].append({"path": priority, "problem": f"{aged} actionable items need aging to Review"})
    # A commit that wrote only some of its notes is a real inconsistency, so it blocks the stamp until resumed.
    for row in vault.unfinished():
        report["issues"].append({"path": "snapshots", "problem": f"Unfinished vault transaction {row['transaction_id']} ({row['status']}, "
                                 f"{len(row['notes'])} notes): run vaultctl.py resume {row['transaction_id']}"})
    if check_parity:
        report["issues"].extend({"path": "boot/skills", "problem": problem} for problem in parity(home or Path.home()))
        try:
            idle = idle_hooks(vault, home or Path.home())
        except Exception:
            idle = []
        if idle:
            report["hooks_idle"] = idle  # informational: installed hooks that have never started a session
        if vault.root == DEFAULT_VAULT.resolve():
            try:  # the runtime baseline is an optional contrib/windows-audit tool
                from vault_runtime import BASELINE, check_runtime
            except ImportError:
                BASELINE = None
            if BASELINE is not None and BASELINE.exists():  # Scheduled tasks are optional; baseline is recorded at installation.
                report["issues"].extend({"path": "runtime", "problem": problem} for problem in check_runtime())
    contract = "10 - Resources/Vault Workflow Contract.md"
    if contract in texts:
        match = re.search(r"<!-- VAULT SCHEMA START -->.*?<!-- VAULT SCHEMA END -->", texts[contract], re.S)
        expected = schema_block()
        if not match:
            report["issues"].append({"path": contract, "problem": "Missing generated schema block"})
        elif match.group(0).replace("\r\n", "\n") != expected:
            if fix:
                info = vault.inspect(contract)
                operations[contract] = {"path": contract, "expected_sha256": info["sha256"],
                                        "edits": [{"old": match.group(0), "new": expected}]}
                report["repairs"].append("Refreshed schema block from vault-schema.json")
            else:
                report["issues"].append({"path": contract, "problem": "Human schema block differs from machine schema"})
    if operations:
        report["commit"] = vault.commit(list(operations.values()), "automation", "Deterministic schema/index/priority hygiene")
    try:
        report["profile_drift"] = profile_drift(vault)  # informational; never blocks the stamp
    except Exception as exc:
        report["profile_drift"] = {"outcome": "error", "error": str(exc)}
    report["outcome"] = "verified" if not report["issues"] else "needs_review"
    atomic_json(vault.state / "hygiene-latest.json", report)
    append_jsonl(vault.state / "outcomes.jsonl", {"at": report["at"], "kind": "hygiene", "outcome": report["outcome"],
                 "notes": report["notes"], "repairs": len(report["repairs"]), "issues": len(report["issues"]),
                 "model": "automation", "usage": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0}, vault.state)
    return report
