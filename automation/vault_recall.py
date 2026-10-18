"""Recall quality, consolidation and fact freshness for a Markdown-only vault.

Nothing here adds a database, embedding or index. Every command reads notes on
demand. The only write is the optional retrieval audit line, made through the
shared writer with the `automation` signature.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re

from vault_core import (MONTHS, VaultError, atomic_json, format_note_time, frontmatter, is_daily,
                        now, read_text)

EVAL_NOTE = "10 - Resources/Recall Eval.md"
MISS_LOG = "00 - Inbox/Retrieval Misses.md"
VOLATILE_NOTES = ("Machine Inventory.md",)
ARCHIVE_PREFIX = "09 - Archive/"
AS_OF = re.compile(r"\(as of ([^)]{6,40})\)", re.IGNORECASE)
DEAD_END_HINT = re.compile(r"\b(failed|fails|broke|broken|did not work|didn't work|dead end|workaround|reverted|"
                           r"abandoned|do instead)\b", re.IGNORECASE)
INLINE_CODE = re.compile(r"`[^`\n]*`")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
MAX_ITEM = 300


def _clip(text):
    text = " ".join(text.split())
    return text if len(text) <= MAX_ITEM else text[:MAX_ITEM - 1] + "…"


def _unfenced_lines(text):
    """Yield (line_number, line) outside fenced code blocks."""
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            yield number, line


def parse_day(value):
    """ISO `2026-09-28` or readable `September 28, 2026`."""
    value = value.strip()
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        pass
    match = re.fullmatch(r"([A-Za-z]+) ([1-9]\d?), (\d{4})", value)
    if match and match.group(1).capitalize() in MONTHS:
        return dt.date(int(match.group(3)), MONTHS.index(match.group(1).capitalize()) + 1, int(match.group(2)))
    return None


def _today():
    return now().date()


def _live_notes(vault):
    """Default retrieval scope: visible notes outside Archive."""
    for path in vault.notes():
        rel = path.relative_to(vault.root).as_posix()
        if not rel.startswith(ARCHIVE_PREFIX):
            yield path, rel


# ---------------------------------------------------------------- recall eval

def load_eval(text):
    """Rows of `| question | expected note | search terms |` from the eval note table."""
    cases = []
    for _, line in _unfenced_lines(text):
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.lstrip().startswith("|") else []
        if len(cells) < 3 or set(cells[0]) <= set("-: ") or cells[0].lower() == "question":
            continue
        expected = WIKILINK.findall(cells[1])
        heading = re.search(r"\[\[[^\]|#]+#([^\]|]+)", cells[1])
        terms = [t.strip().lower() for t in cells[2].split(",") if t.strip()]
        if cells[0] and expected and terms:
            cases.append({"question": cells[0], "expected": expected[0].strip(), "terms": terms,
                          "heading": heading.group(1).strip() if heading else None})
    return cases


def has_heading(text, heading):
    return any(re.fullmatch(r"#{1,6}\s+" + re.escape(heading) + r"\s*", line) for _, line in _unfenced_lines(text))


def score_note(stem, text, terms):
    """Mirror the contract's retrieval order: filename, then headings/links, then body."""
    name = stem.lower()
    lowered = text.lower()
    headings = "\n".join(line for _, line in _unfenced_lines(text) if line.startswith("#")).lower()
    links = " ".join(WIKILINK.findall(text)).lower()
    score = 0
    for term in terms:
        if term in name:
            score += 8
        if term in headings:
            score += 4
        if term in links:
            score += 2
        score += min(lowered.count(term), 3)
    return score


def recall_eval(vault, top_k=5, record=False):
    info = vault.inspect(EVAL_NOTE)
    if info["text"] is None:
        raise VaultError("Missing eval note: " + EVAL_NOTE)
    cases = load_eval(info["text"])
    if not cases:
        raise VaultError("Eval note has no | question | [[expected note]] | terms | rows")
    corpus = [(path.stem, rel, read_text(path)) for path, rel in _live_notes(vault) if rel != EVAL_NOTE]
    stems = {stem.lower() for stem, _, _ in corpus}
    results = []
    for case in cases:
        ranked = sorted(((score_note(stem, text, case["terms"]), len(rel), stem) for stem, rel, text in corpus),
                        key=lambda row: (-row[0], row[1]))
        ranked = [row for row in ranked if row[0] > 0]
        order = [stem.lower() for _, _, stem in ranked]
        target = case["expected"].lower()
        rank = order.index(target) + 1 if target in order else None
        note_text = next((text for stem, _, text in corpus if stem.lower() == target), "")
        missing_heading = bool(case.get("heading")) and not has_heading(note_text, case["heading"])
        results.append({**case, "rank": rank, "found": rank is not None and rank <= top_k and not missing_heading,
                        "missing_note": target not in stems, "missing_heading": missing_heading,
                        "top": [stem for _, _, stem in ranked[:top_k]]})
    misses = [r for r in results if not r["found"]]
    report = {"outcome": "needs_review" if misses else "passed", "questions": len(results),
              "found": len(results) - len(misses), "top_k": top_k,
              "recall_at_k": round((len(results) - len(misses)) / len(results), 3),
              "misses": [{k: r[k] for k in ("question", "expected", "rank", "missing_note", "missing_heading", "top")} for r in misses],
              "method": "Lexical ranking over live notes: filename, headings, wikilinks, body (no index)"}
    if record:
        report["recorded"] = record_eval(vault, report)
    return report


def record_eval(vault, report):
    """Append one dated result line to the Inbox retrieval audit through the shared writer."""
    info = vault.inspect(MISS_LOG)
    stamp = format_note_time()
    line = f"- {stamp.split(' at ')[0]}: {report['found']}/{report['questions']} found in top {report['top_k']}"
    if report["misses"]:
        line += "; misses: " + "; ".join(
            f"\"{m['question']}\" (expected [[{m['expected']}]], rank {m['rank'] or 'none'}"
            + (", note missing" if m["missing_note"] else "") + ")" for m in report["misses"])
    line += " `(automation)`"
    text = info["text"]
    if text is None:
        op = {"path": MISS_LOG, "expected_sha256": None, "content": (
            "---\nstatus: active\nproject: meta\ntype: log\nupdated_by: automation\n"
            f"updated: {stamp}\n---\n\n# Retrieval Misses\n\n"
            "Results of `vaultctl.py recall-eval --record`, newest last. Each line is one run of the questions in "
            "[[Recall Eval]]. A database or index is justified only by a persistent, non-trivial miss list here.\n\n"
            "## Runs\n\n" + line + "\n")}
    else:
        op = {"path": MISS_LOG, "expected_sha256": info["sha256"],
              "append": ("" if text.endswith("\n") else "\n") + line + "\n"}
    receipt = vault.commit([op], "automation", "Record retrieval eval result")
    return {"path": MISS_LOG, "transaction_id": receipt.get("transaction_id")}


# ------------------------------------------------------------- consolidation

def daily_sessions(text):
    """Split a daily note into sessions with their `###` sections as item lists."""
    sessions, current, section = [], None, None
    for _, line in _unfenced_lines(text):
        if line.startswith("## Session"):
            current = {"heading": line.strip(), "sections": {}}
            sessions.append(current)
            section = None
        elif line.startswith("## "):
            current = section = None
        elif current is not None and line.startswith("### "):
            section = line[4:].strip()
            current["sections"].setdefault(section, [])
        elif current is not None and section and line.lstrip().startswith("- "):
            item = line.lstrip()[2:].strip()
            if item and item.lower().rstrip(".") != "none":
                current["sections"][section].append(item)
    return sessions


def consolidation_state(vault):
    path = vault.state / "consolidation.json"
    return path, (json.loads(read_text(path)) if path.exists() else {})


def _leading_day(value):
    match = re.match(r"\s*(\d{4}-\d{2}-\d{2}|[A-Za-z]+ [1-9]\d?, \d{4})", value or "")
    return parse_day(match.group(1)) if match else None


def note_start(vault, note):
    """Default window for --note: the older of its handoff `_Last updated:` date and frontmatter `updated`."""
    path = next((p for p, _ in _live_notes(vault) if not is_daily(p) and p.stem.lower() == note.strip().lower()), None)
    if path is None:
        raise VaultError("--note: no live note named " + note)
    text = read_text(path)
    fields, _ = frontmatter(text)
    handoff = re.search(r"^_Last updated:\s*(.+)$", text, re.M)
    dates = [d for d in (_leading_day(fields.get("updated", "")), _leading_day(handoff.group(1) if handoff else "")) if d]
    return min(dates) if dates else None


def _mentions(session, note):
    key = note.strip().lower()
    if key in session["heading"].lower():
        return True
    return any(link.strip().lower() == key for item in session["sections"].get("Notes Touched", []) for link in WIKILINK.findall(item))


def consolidate_context(vault, days=None, since=None, note=None):
    """Digest of daily sessions for a consolidation pass or a project resume. Read-only.

    Window precedence: --since, then an explicit --days, then (with --note) the
    note's own handoff/update date, then the stored mark, then seven days.
    """
    state_path, state = consolidation_state(vault)
    today = _today()
    start = None
    if since:
        start = parse_day(since)
        if start is None:
            raise VaultError("--since needs YYYY-MM-DD")
    elif days is not None:
        start = today - dt.timedelta(days=max(days, 1) - 1)
    elif note:
        start = note_start(vault, note)
    if start is None:
        if state.get("through"):
            start = dt.date.fromisoformat(state["through"]) + dt.timedelta(days=1)
        else:
            start = today - dt.timedelta(days=6)
    stems = {path.stem.lower() for path, _ in _live_notes(vault)}
    listed = []
    touched, open_items, decisions, dead_ends, unresolved, sessions_seen = {}, [], [], [], set(), 0
    covered = []
    for path, rel in _live_notes(vault):
        if not is_daily(path):
            continue
        day = dt.date.fromisoformat(path.stem)
        if not start <= day <= today:
            continue
        covered.append(path.stem)
        for session in daily_sessions(read_text(path)):
            if note and not _mentions(session, note):
                continue
            sessions_seen += 1
            ref = {"daily": rel, "session": session["heading"]}
            if note:
                listed.append(ref)
            sections = session["sections"]
            for item in sections.get("Notes Touched", []):
                for link in WIKILINK.findall(item):
                    key = link.strip()
                    touched.setdefault(key, []).append(ref)
                    if key.lower() not in stems:
                        unresolved.add(key)
            open_items += [{**ref, "item": _clip(i)} for i in sections.get("What's Still In Progress", [])]
            decisions += [{**ref, "item": _clip(i)} for i in sections.get("Decisions Made", [])]
            dead_ends += [{**ref, "item": _clip(i)} for s in ("What Got Done", "What's Still In Progress")
                          for i in sections.get(s, []) if DEAD_END_HINT.search(i)]
    result = {"outcome": "context", "from": start.isoformat(), "through": today.isoformat(),
              "days_with_notes": sorted(covered), "sessions": sessions_seen,
              "last_marked": state.get("through"), "state_file": str(state_path),
              "touched_notes": sorted(({"note": k, "sessions": len(v), "refs": v[:5]} for k, v in touched.items()),
                                      key=lambda row: -row["sessions"]),
              "open_items": open_items, "decisions": decisions, "dead_end_candidates": dead_ends,
              "unresolved_links": sorted(unresolved),
              "next": "Fully read the listed sessions before proposing topic, Active Priorities, Decisions or Dead Ends "
                      "updates; write through commit/checkpoint, then run consolidate-context --mark <through>."}
    if note:
        result.update(note=note, listed_sessions=listed,
                      next=f"Read only these {len(listed)} sessions with daily-context and the matching session bodies; "
                           "the --note view is stateless and never moves the consolidation mark.")
    return result


def mark_consolidated(vault, through):
    day = parse_day(through)
    if day is None or day > _today():
        raise VaultError("--mark needs a past or current YYYY-MM-DD")
    path, state = consolidation_state(vault)
    state.update(through=day.isoformat(), marked_at=now().isoformat())
    atomic_json(path, state)
    return {"outcome": "marked", "through": day.isoformat(), "state_file": str(path)}


# ------------------------------------------------------------- fact freshness

HANDOFF_HEADING = "## Handoff — resume here"
HANDOFF_LIMIT = 4000


def handoff_report(rel, text, report):
    """Measurement only: a handoff older than its note, oversized, or under a nonstandard heading."""
    lines = [line for _, line in _unfenced_lines(text)]
    start = next((i for i, line in enumerate(lines) if line.startswith("## Handoff")), None)
    if start is None:
        return
    if lines[start].strip() != HANDOFF_HEADING:
        report["nonstandard_heading"].append({"path": rel, "heading": lines[start][:60]})
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    block = "\n".join(lines[start:end])
    if len(block) > HANDOFF_LIMIT:
        report["oversized"].append({"path": rel, "chars": len(block)})
    stamp = re.search(r"^_Last updated:\s*(.+)$", block, re.M)
    fields, _ = frontmatter(text)
    written, refreshed = _leading_day(fields.get("updated", "")), _leading_day(stamp.group(1) if stamp else "")
    if written and refreshed and (written - refreshed).days > 2:
        report["stale"].append({"path": rel, "handoff": refreshed.isoformat(), "note_updated": written.isoformat()})


def fact_freshness(vault, max_age_days=90):
    """Stale `(as of <date>)` markers and volatile notes that carry none. Read-only."""
    today = _today()
    stale, unparsed, fresh, unmarked = [], [], 0, []
    handoffs = {"stale": [], "oversized": [], "nonstandard_heading": []}
    for path, rel in _live_notes(vault):
        if is_daily(path):
            continue  # Daily history is dated by construction.
        text = read_text(path)
        markers = 0
        for number, line in _unfenced_lines(text):
            # Inline code shows the convention; it is not a dated fact.
            for match in AS_OF.finditer(INLINE_CODE.sub("", line)):
                markers += 1
                day = parse_day(match.group(1))
                if day is None:
                    unparsed.append({"path": rel, "line": number, "marker": match.group(0)})
                elif (today - day).days > max_age_days:
                    stale.append({"path": rel, "line": number, "as_of": day.isoformat(),
                                  "age_days": (today - day).days, "text": _clip(line)})
                else:
                    fresh += 1
        if path.name in VOLATILE_NOTES and markers == 0:
            fields, _ = frontmatter(text)
            unmarked.append({"path": rel, "updated": fields.get("updated")})
        handoff_report(rel, text, handoffs)
    issues = stale or unparsed or unmarked
    return {"outcome": "needs_review" if issues else "passed", "max_age_days": max_age_days,
            "fresh_markers": fresh, "stale": stale, "unparsed": unparsed, "volatile_without_markers": unmarked,
            "handoffs": handoffs,
            "convention": "Suffix a fact that can change with (as of YYYY-MM-DD) or (as of Month D, YYYY); "
                          "re-verify before relying on a stale one."}


# -------------------------------------------------------------- session brief

BRIEF_CAP = 700
BRIEF_LINE = 160
HOOK_ERROR_DAYS = 7


def _clip_to(text, limit):
    """Clip to a UTF-8 byte budget, since the brief's cap is in bytes."""
    text = " ".join(text.split())
    if len(text.encode("utf-8")) <= limit:
        return text
    while text and len(text.encode("utf-8")) > limit - 3:
        text = text[:-1]
    return text + "…"


def latest_daily(vault):
    """The newest dated daily note: day, Open line and session headings, read without the bodies."""
    dailies = [p for p in vault.notes() if is_daily(p)]
    if not dailies:
        return None
    path = max(dailies, key=lambda p: p.stem)  # stems are ISO dates; month folders sort by month, not year
    open_line, sessions = None, []
    for _, line in _unfenced_lines(read_text(path)):
        if line.startswith("**Open for tomorrow:**"):
            open_line = line[len("**Open for tomorrow:**"):].strip()
        elif re.match(r"^## Session \d+\b", line):
            sessions.append(line[3:].strip())
    return {"day": path.stem, "open": open_line, "sessions": sessions}


def active_now(vault):
    """Actionable bullets under Active Now, without their touched markers."""
    info = vault.inspect("Active Priorities.md")
    if info["text"] is None:
        return []
    section = re.search(r"^## Active Now\r?\n(.*?)(?=^## |\Z)", info["text"], re.S | re.M)
    items = []
    for line in (section.group(1).splitlines() if section else []):
        if line.startswith("- ") and line.strip() != "- None":
            items.append(re.sub(r"\s*`touched: \d{4}-\d{2}-\d{2}`", "", line[2:]).strip())
    return items


def recent_hook_errors(automation_dir, days=HOOK_ERROR_DAYS):
    """Fail-open hook errors nobody would otherwise see."""
    path = Path(automation_dir) / "hook-errors.jsonl"
    if not path.exists():
        return 0
    since = now() - dt.timedelta(days=days)
    count = 0
    for line in read_text(path).splitlines():
        try:
            at = dt.datetime.fromisoformat(json.loads(line)["at"])
            if at.tzinfo is None:
                at = at.astimezone()
            if at >= since:
                count += 1
        except (ValueError, KeyError, TypeError):
            continue
    return count


def session_brief(vault, automation_dir=None, cap=BRIEF_CAP):
    """Plain-text continuity for the start of a session: navigation, never evidence. Reads only; never raises."""
    if not (vault.root / "VAULT-INDEX.md").is_file():
        return f"Brain: no vault at {vault.root}; run the Agent Brain setup."
    lines = []  # (priority, text); the lowest priority is dropped first under the cap

    def add(priority, text):
        lines.append((priority, _clip_to(text, BRIEF_LINE)))

    try:
        daily, failure = latest_daily(vault), None
    except Exception as exc:
        daily, failure = None, exc
    if failure is not None:
        add(9, f"Brain: could not read the latest daily note ({type(failure).__name__}: {failure}); check it before relying on history.")
    elif daily is None:
        add(9, "Brain: no sessions recorded yet.")
    else:
        add(9, f"Brain: last day {daily['day']}" + (f"; open: {daily['open']}" if daily["open"] else ""))
        for index, heading in enumerate(reversed(daily["sessions"][-2:])):
            add(6 - index, ("Last session: " if index == 0 else "Before that: ") + heading)
    try:
        items = active_now(vault)
    except Exception:
        items = []
    if items:
        add(5, "Active Now: " + " · ".join(_clip_to(item, 80) for item in items[:5]))
    if automation_dir:
        try:
            errors = recent_hook_errors(automation_dir)
        except Exception:
            errors = 0
        if errors:
            add(7, f"Hook errors: {errors} in the last {HOOK_ERROR_DAYS} days; see {Path(automation_dir) / 'hook-errors.jsonl'}")
    add(8, "Read VAULT-INDEX.md once before substantive work; checkpoint through vaultctl.py before handing back. This brief is navigation, not evidence.")
    kept = set(range(len(lines)))

    def size():
        return len("\n".join(lines[i][1] for i in sorted(kept)).encode("utf-8"))

    for i in sorted(range(len(lines)), key=lambda i: lines[i][0]):
        if size() <= cap:
            break
        if lines[i][0] < 8:
            kept.discard(i)
    return "\n".join(lines[i][1] for i in sorted(kept))
