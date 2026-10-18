"""Read-only wikilink audit in pure Python: missing targets, ambiguous names, unmatched headings or blocks, orphans.

It follows Obsidian's rules closely enough for a report, not as a parser of record: a bare name resolves by file
name anywhere in the vault, a path resolves by suffix, `#Heading` and `#^block` are checked in the target. Archive
notes are not sources, though archived targets resolve. Nothing is fetched, created, merged or rewritten.
"""
from __future__ import annotations

from pathlib import Path
import re

from vault_core import read_text

LINK = re.compile(r"(!?)\[\[([^\[\]|#^]*)((?:#\^?[^\[\]|]*)?)(?:\|[^\[\]]*)?\]\]")
FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.S | re.M)
INLINE = re.compile(r"`[^`\n]*`")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)
BLOCK = re.compile(r"\s\^([A-Za-z0-9-]+)\s*$", re.M)
ARCHIVE = "09 - Archive"
SHOWN = 20


def _norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[*_`\[\]]", "", text)).strip().lower()


def _files(root):
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if path.is_file() and not any(part.startswith(".") for part in rel.parts):
            yield rel


def audit(vault, full=False):
    root = vault.root
    files = sorted(_files(root), key=lambda p: p.as_posix().lower())
    by_name = {}
    for rel in files:
        by_name.setdefault(rel.name.lower(), []).append(rel)
        if rel.suffix.lower() == ".md":
            by_name.setdefault(rel.stem.lower(), []).append(rel)
    texts = {}

    def text_of(rel):
        if rel not in texts:
            texts[rel] = read_text(root / rel) if rel.suffix.lower() == ".md" else ""
        return texts[rel]

    def resolve(target):
        target = target.strip().replace("\\", "/")
        name = target.rsplit("/", 1)[-1].lower()
        candidates = by_name.get(name, [])
        if "/" in target:
            wanted = target.lower()
            candidates = [c for c in candidates if c.as_posix().lower().endswith(wanted) or c.with_suffix("").as_posix().lower().endswith(wanted)]
        return candidates

    report = {"missing": [], "ambiguous": [], "fragments": [], "orphans": []}
    incoming = {rel: 0 for rel in files if rel.suffix.lower() == ".md"}
    sources = [rel for rel in files if rel.suffix.lower() == ".md" and rel.parts[0] != ARCHIVE]
    for rel in sources:
        body = INLINE.sub("", FENCE.sub("", text_of(rel)))
        for embed, target, fragment in LINK.findall(body):
            link = f"{'!' if embed else ''}[[{target}{fragment}]]"
            if not target.strip():
                found = [rel]  # a same-note heading or block link
            else:
                found = resolve(target)
            if not found:
                report["missing"].append({"source": rel.as_posix(), "link": link})
                continue
            if len(found) > 1 and "/" not in target:
                shortest = min(found, key=lambda p: (len(p.parts), p.as_posix().lower()))
                report["ambiguous"].append({"source": rel.as_posix(), "link": link, "resolves_to": shortest.as_posix(),
                                            "candidates": [p.as_posix() for p in found]})
                found = [shortest]
            hit = found[0]
            if hit != rel and hit in incoming:
                incoming[hit] += 1
            if fragment and hit.suffix.lower() == ".md" and hit.parts[0] != ARCHIVE:
                content = text_of(hit)
                if fragment.startswith("#^"):
                    ok = fragment[2:] in BLOCK.findall(content)
                else:
                    wanted = _norm(fragment[1:].split("#")[-1])
                    ok = wanted in {_norm(h) for h in HEADING.findall(INLINE.sub("", FENCE.sub("", content)))}
                if not ok:
                    report["fragments"].append({"source": rel.as_posix(), "link": link})
    for rel, count in incoming.items():
        top = rel.parts[0]
        if count == 0 and len(rel.parts) > 1 and top[:2] in ("02", "03", "04", "05", "06", "07", "10") and rel.stem != top:
            report["orphans"].append(rel.as_posix())
    counts = {key: len(value) for key, value in report.items()}
    result = {"outcome": "needs_review" if counts["missing"] or counts["fragments"] else "clean", "notes": len(sources), "counts": counts}
    result.update({key: value if full else value[:SHOWN] for key, value in report.items()})
    return result
