"""Deterministic vault hygiene. No model invocation and no automatic archiving."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re

from vault_core import (DEFAULT_VAULT, HERE, SCHEMA, VaultError, append_jsonl, atomic_json, file_lock,
                        frontmatter, is_daily, now, read_text, sha, validate)

FOLDER_PROJECTS = SCHEMA["folder_projects"]


def schema_block():
    quote = lambda values: ", ".join("`" + value + "`" for value in values)
    return "\n".join([
        "<!-- VAULT SCHEMA START -->",
        "- Required keys: " + quote(SCHEMA["required"]) + ".",
        "- Optional existing key: " + quote(SCHEMA["optional"]) + ". No other keys.",
        "- Status: " + quote(SCHEMA["status"]) + ".",
        "- Project: any kebab-case slug; optional project_allowlist in vault-schema.json. Starter values: " + quote(SCHEMA["project"]) + ".",
        "- Type: " + quote(SCHEMA["type"]) + ".",
        "- Signature: lowercase model label/ID, `human`, `automation`, or `unknown-model`; legacy tags remain valid in history.",
        "- Updated: an actual calendar date in `YYYY-MM-DD`, taken from the system clock at the write.",
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
                "updated_by": "automation", "updated": now().date().isoformat()}
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
        addition = ""
        last_category = None
        for category, line in moved:
            if category != last_category:
                addition += newline + category + newline
                last_category = category
            addition += line + newline
        chunks[review] = chunks[review].rstrip("\r\n") + newline + addition + newline
    return "".join(chunks), len(moved), count_active


def parity(home):
    home = Path(home)
    issues = []
    clients = [(home / ".codex", "AGENTS.md"), (home / ".claude", "CLAUDE.md")]
    # A client participates when its boot file is installed. A single-client
    # installation still checks its skills without demanding another client.
    clients = [(root, boot) for root, boot in clients if (root / boot).exists()]
    if not clients:
        return ["No installed client boot files"]
    for skill in ("obsidian-vault", "handoff"):
        copies = []
        for root, _ in clients:
            path = root / "skills" / skill / "SKILL.md"
            if not path.exists():
                issues.append("Missing installed skill: " + str(path))
            else:
                copies.append(path.read_bytes())
        if len(copies) == 2 and copies[0] != copies[1]:
            issues.append("Skill mirror mismatch: " + skill)
    blocks = []
    for root, boot in clients:
        path = root / boot
        match = re.search(r"<!-- SHARED VAULT RULES START -->\s*(.*?)\s*<!-- SHARED VAULT RULES END -->", read_text(path), re.S)
        if not match:
            issues.append("Missing shared-rule block: " + str(path))
        else:
            blocks.append(match.group(1))
    if len(blocks) == 2 and blocks[0] != blocks[1]:
        issues.append("Boot shared-rule blocks differ")
    return issues


def daily_structure(text, path=None):
    issues = []
    _, body = frontmatter(text)
    for pattern, problem in [(r"^# \w+, \w+ \d{1,2}, \d{4}\r?$", "Missing human-readable date heading"),
                             (r"^\*\*Open for tomorrow:\*\*[^\r\n]*", "Missing Open for tomorrow line"),
                             (r"^## Index\r?$", "Missing daily Index")]:
        # The Open-line contract was introduced September 3. Do not rewrite
        # older immutable history to retrofit a later template convention.
        legacy = path is not None and is_daily(path) and Path(path).stem < "2026-09-03"
        if problem == "Missing Open for tomorrow line" and legacy:
            continue
        if not re.search(pattern, body, re.M):
            issues.append(problem)
    return issues


def hygiene(vault, fix=False, check_parity=True, home=None):
    """Fully scan every live note and return a signed machine-readable report."""
    report = {"version": 2, "at": now().isoformat(), "writer": "automation", "notes": 0,
              "issues": [], "repairs": [], "aged": 0, "cost_usd": 0, "model_calls": 0}
    operations = {}
    notes = vault.notes()
    texts = {}
    for path in notes:
        info = vault.inspect(path)
        rel, text = info["path"], info["text"]
        texts[rel] = text
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
        if not folder.is_dir() or folder.name[:2] not in ("02", "03", "04", "05", "06", "07"):
            continue
        index_path = folder / (folder.name + ".md")
        info = vault.inspect(index_path)
        rel, text = info["path"], texts.get(info["path"], "")
        if not text:
            report["issues"].append({"path": rel, "problem": "Missing required folder index"})
            continue
        revised = text
        for note in [p for p in notes if folder in p.parents and p != index_path]:
            if not re.search(r"\[\[" + re.escape(note.stem) + r"(?:[|#][^\]]*)?\]\]", revised):
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
        if count_active > 5:
            report["issues"].append({"path": priority, "problem": "Active Now exceeds five committed items"})
        if aged:
            if fix:
                info = vault.inspect(priority)
                operations[priority] = {"path": priority, "expected_sha256": info["sha256"], "content": revised}
                report["aged"] = aged
            else:
                report["issues"].append({"path": priority, "problem": f"{aged} actionable items need aging to Review"})
    if check_parity:
        report["issues"].extend({"path": "boot/skills", "problem": problem} for problem in parity(home or Path.home()))
        if vault.root == DEFAULT_VAULT.resolve():
            from vault_runtime import BASELINE, check_runtime
            if BASELINE.exists():  # Scheduled tasks are optional; baseline is recorded at installation.
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
    report["outcome"] = "verified" if not report["issues"] else "needs_review"
    atomic_json(vault.state / "hygiene-latest.json", report)
    append_jsonl(vault.state / "outcomes.jsonl", {"at": report["at"], "kind": "hygiene", "outcome": report["outcome"],
                 "notes": report["notes"], "repairs": len(report["repairs"]), "issues": len(report["issues"]),
                 "model": "automation", "usage": {"input_tokens": 0, "output_tokens": 0}, "cost_usd": 0}, vault.state)
    return report
