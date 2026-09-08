"""Shared, stdlib-only vault validation, locking, snapshots and verified commits.

Markdown is canonical. State files contain operational receipts, never a second
knowledge store. No provider calls or scheduled tasks are started by importing.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

HERE = Path(__file__).resolve().parent
DEFAULT_AUTOMATION = Path(os.environ.get("BRAIN_AUTOMATION_DIR") or os.environ.get("VAULT_AUTOMATION_DIR") or HERE).expanduser()
DEFAULT_VAULT = Path(os.environ.get("BRAIN_VAULT_ROOT") or Path.home() / "Documents" / "Brain").expanduser()
DEFAULT_STATE = Path(os.environ.get("BRAIN_STATE_DIR") or DEFAULT_AUTOMATION / "state-v2").expanduser()
DEFAULT_BACKUPS = Path(os.environ.get("BRAIN_BACKUPS_DIR") or DEFAULT_VAULT.parent / (DEFAULT_VAULT.name + " Backups") / "versions").expanduser()
SCHEMA = json.loads((HERE / "vault-schema.json").read_text(encoding="utf-8-sig"))
DAILY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


class VaultError(Exception):
    pass


class Conflict(VaultError):
    pass


def now():
    return dt.datetime.now().astimezone()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def text_bytes(text):
    return text.encode("utf-8")


def read_text(path):
    return Path(path).read_bytes().decode("utf-8-sig")


def model_label(model_id):
    """Label a VERIFIED runtime model id; never infer it from an agent brand."""
    if not isinstance(model_id, str) or not model_id.strip():
        raise VaultError("Actual model id is required; do not guess from the client name")
    name = model_id.strip().lower()
    if name in SCHEMA["model_labels"]:
        return SCHEMA["model_labels"][name]
    match = re.fullmatch(r"claude-(opus|sonnet|haiku|fable)-(\d+)(?:[.-](\d+))?(?:-\d{8})?", name)
    if match:
        family, major, minor = match.groups()
        return family + " " + major + ("." + minor if minor else "")
    if not re.fullmatch(SCHEMA["signature_pattern"], name):
        raise VaultError("Invalid model identifier")
    if name in SCHEMA["legacy_signatures"]:
        raise VaultError("New model-authored entries need the model, not claude/codex")
    return name


def scalar(raw):
    raw = raw.strip()
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except ValueError as exc:
            raise VaultError("Malformed quoted scalar") from exc
        if not isinstance(value, str):
            raise VaultError("Expected a scalar string")
        return value
    if raw.startswith("'"):
        if not raw.endswith("'") or len(raw) < 2:
            raise VaultError("Unclosed quoted scalar")
        return raw[1:-1].replace("''", "'")
    value = re.split(r"\s+#", raw, maxsplit=1)[0].rstrip()
    if not value or value[0] in "[{|>" or value in ("null", "~"):
        raise VaultError("Required fields must be nonempty scalar strings")
    return value


def frontmatter(text):
    """Parse this vault's deliberately flat YAML contract, rejecting ambiguity.

    Required fields are scalars. Aliases accepts an inline string list or an
    indented/block sequence. General YAML nesting/tags are outside this schema.
    """
    text = text.lstrip("\ufeff")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise VaultError("Missing opening frontmatter fence")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise VaultError("Missing closing frontmatter fence")
    fields = {}
    alias_sequence = False
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if alias_sequence and re.match(r"^\s*-\s+", line):
            fields["aliases"].append(scalar(re.sub(r"^\s*-\s+", "", stripped)))
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*?)\s*$", line)
        if not match:
            raise VaultError("Unsupported or malformed YAML line: " + stripped[:80])
        key, raw = match.groups()
        if key in fields:
            raise VaultError("Duplicate frontmatter key: " + key)
        alias_sequence = False
        if key == "aliases":
            if not raw:
                fields[key] = []
                alias_sequence = True
            elif raw.startswith("[") and raw.endswith("]"):
                inner = raw[1:-1].strip()
                # Existing aliases are simple strings. Reject nested syntax.
                fields[key] = [scalar(x) for x in re.split(r",\s*(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", inner)] if inner else []
            else:
                fields[key] = [scalar(raw)]
        else:
            fields[key] = scalar(raw)
    return fields, "".join(lines[end + 1:])


def is_daily(path):
    p = Path(path)
    return "01 - Daily Notes" in p.parts and bool(DAILY_RE.fullmatch(p.name))


def validate(text, path="note.md"):
    issues = []
    try:
        fields, body = frontmatter(text)
    except VaultError as exc:
        return [str(exc)]
    missing = set(SCHEMA["required"]) - fields.keys()
    extra = fields.keys() - set(SCHEMA["required"] + SCHEMA["optional"])
    if missing:
        issues.append("Missing required keys: " + ", ".join(sorted(missing)))
    if extra:
        issues.append("Undeclared keys: " + ", ".join(sorted(extra)))
    for key in ("status", "type"):
        if key in fields and fields[key] not in SCHEMA[key]:
            issues.append("Invalid " + key + ": " + fields[key])
    if "project" in fields:
        allowlist = SCHEMA.get("project_allowlist")
        if not re.fullmatch(SCHEMA["project_pattern"], fields["project"]) or (allowlist is not None and fields["project"] not in allowlist):
            issues.append("Invalid project: " + fields["project"])
    if "updated_by" in fields and not re.fullmatch(SCHEMA["signature_pattern"], fields["updated_by"]):
        issues.append("Invalid model signature")
    if "updated" in fields:
        try:
            manual_template = str(path).replace("\\", "/").endswith("10 - Resources/Templates/Manual Daily Note Template.md")
            if manual_template and fields["updated"] == "{{date:YYYY-MM-DD}}":
                pass  # The single output template is expanded by Obsidian.
            elif not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fields["updated"]):
                raise ValueError()
            else:
                dt.date.fromisoformat(fields["updated"])
        except ValueError:
            issues.append("updated must be an actual YYYY-MM-DD calendar date")
    if is_daily(path):
        for key, value in (("status", "active"), ("project", "personal"), ("type", "log")):
            if fields.get(key) != value:
                issues.append("Daily note requires " + key + ": " + value)
    return issues


def restamp(text, signer, date=None):
    if not re.fullmatch(SCHEMA["signature_pattern"], signer):
        raise VaultError("Invalid signer")
    fields, _ = frontmatter(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    end = re.search(r"^---\s*\r?$", text, re.M)
    # Replace only the leading fenced block, never matches in body examples.
    lines = text.splitlines(keepends=True)
    fence = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    header = "".join(lines[:fence + 1])
    for key, value in (("updated_by", signer), ("updated", date or now().date().isoformat())):
        pattern = re.compile(r"^" + key + r":[^\r\n]*", re.M)
        if key in fields:
            header = pattern.sub(key + ": " + value, header, count=1)
        else:
            pos = header.rfind("---")
            header = header[:pos] + key + ": " + value + newline + header[pos:]
    return header + "".join(lines[fence + 1:])


def ensure_new_daily_sections(text):
    if text.strip() and not text.lstrip().startswith("## Session"):
        raise VaultError("Only complete new session sections may be appended")
    blocks = re.split(r"(?=^## Session\b)", text, flags=re.M)
    for block in blocks:
        if not block.startswith("## Session"):
            continue
        heading = block.splitlines()[0]
        if not re.search(r"\d{1,2}:\d{2}(?:\s*[AP]M)?", heading, re.I):
            raise VaultError("New session heading requires local time")
        if not re.search(r"`[a-z0-9][a-z0-9 ._-]*`\s*$", heading):
            raise VaultError("New session heading requires model signature")
        found = re.findall(r"^### (.+?)\r?$", block, re.M)
        if found != SCHEMA["daily_sections"]:
            raise VaultError("New session must contain the five ordered sections")


def assert_daily_append(before, after):
    """Existing session bytes are immutable; only header/Open/Index may change."""
    if not before:
        _, body = frontmatter(after)
        match = re.search(r"^## Session\b", body, re.M)
        if not match:
            raise VaultError("New daily note requires a session")
        ensure_new_daily_sections(body[match.start():])
        return
    _, old_body = frontmatter(before)
    _, new_body = frontmatter(after)
    old_match = re.search(r"^## Session\b", old_body, re.M)
    new_match = re.search(r"^## Session\b", new_body, re.M)
    old_prefix = old_body[:old_match.start()] if old_match else old_body
    new_prefix = new_body[:new_match.start()] if new_match else new_body
    old_sessions = old_body[old_match.start():] if old_match else ""
    new_sessions = new_body[new_match.start():] if new_match else ""
    if not new_sessions.startswith(old_sessions):
        raise VaultError("Existing daily session bytes changed")
    added = new_sessions[len(old_sessions):]
    ensure_new_daily_sections(added.lstrip("\r\n"))

    def prefix_parts(prefix):
        prefix = re.sub(r"^\*\*Open for tomorrow:\*\*[^\r\n]*", "**Open for tomorrow:**", prefix, flags=re.M)
        match = re.search(r"^## Index[ \t]*\r?$", prefix, re.M)
        if not match:
            raise VaultError("Daily note requires an Index block")
        return prefix[:match.end()], prefix[match.end():].splitlines(keepends=True)
    old_head, old_index = prefix_parts(old_prefix)
    new_head, new_index = prefix_parts(new_prefix)
    if old_head != new_head:
        raise VaultError("Daily header outside frontmatter/Open changed")
    pos = 0
    for line in new_index:
        if pos < len(old_index) and line == old_index[pos]:
            pos += 1
        elif line.strip() and not (line.startswith("- **") and re.search(r"`\([a-z0-9][a-z0-9 ._-]*\)`\s*$", line)):
            raise VaultError("Only signed Index bullets may be inserted")
    if pos != len(old_index):
        raise VaultError("An existing daily Index line changed or disappeared")


@contextlib.contextmanager
def file_lock(path, timeout=15):
    """OS-held advisory lock; a terminated process releases it automatically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if handle.seek(0, 2) == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + timeout
    while True:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() >= deadline:
                handle.close()
                raise Conflict("Lock timeout: " + path.name)
            time.sleep(0.05)
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("xb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def atomic_json(path, data):
    atomic_bytes(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def append_jsonl(path, data, state=DEFAULT_STATE):
    path = Path(path)
    lock = Path(state) / "locks" / (sha(str(path.resolve()).encode()) + ".lock")
    with file_lock(lock):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as out:
            out.write((json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
            out.flush()
            os.fsync(out.fileno())


class Vault:
    def __init__(self, root=DEFAULT_VAULT, state=DEFAULT_STATE, backups=DEFAULT_BACKUPS):
        self.root = Path(root).resolve()
        self.state = Path(state).resolve()
        self.backups = Path(backups).resolve()

    def path(self, value, frozen=False):
        value = str(value).replace("\\", "/")
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        candidate = candidate.resolve()
        try:
            relative = candidate.relative_to(self.root)
        except ValueError as exc:
            raise VaultError("Path escapes vault") from exc
        if candidate.suffix.lower() != ".md" or any(p.startswith(".") for p in relative.parts):
            raise VaultError("Only visible Markdown notes are writable")
        if not frozen and any(relative.as_posix().startswith(p + "/") for p in SCHEMA["exempt"]):
            raise VaultError("Frozen archive is read-only")
        return candidate

    def inspect(self, value):
        path = self.path(value)
        data = path.read_bytes() if path.exists() else None
        return {"path": path.relative_to(self.root).as_posix(), "sha256": sha(data) if data is not None else None,
                "text": data.decode("utf-8-sig") if data is not None else None}

    def notes(self):
        return sorted(p for p in self.root.rglob("*.md") if not any(x.startswith(".") for x in p.relative_to(self.root).parts)
                      and not any(p.relative_to(self.root).as_posix().startswith(x + "/") for x in SCHEMA["exempt"]))

    def commit(self, operations, signer, reason, transaction_id=None, restore=False):
        if not operations:
            raise VaultError("Empty commit is not a verified write")
        if len(operations) > 100:
            raise VaultError("Commit exceeds the 100-note bound")
        if signer in SCHEMA["legacy_signatures"] and not restore:
            raise VaultError("New writes require the runtime model signature")
        txid = transaction_id or (now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", txid):
            raise VaultError("Invalid transaction id")
        manifest_path = self.backups / txid / "manifest.json"
        with file_lock(self.state / "locks" / "commits.lock"):
            if manifest_path.exists():
                manifest = json.loads(read_text(manifest_path))
                if manifest.get("root") != str(self.root):
                    raise VaultError("Transaction belongs to a different vault")
                if manifest.get("signer") != signer or manifest.get("reason") != reason:
                    raise VaultError("Transaction identity does not match the prepared commit")
                # Resume a partial commit from immutable prepared bytes. Do not
                # re-run a model or apply a newly generated append on retry.
                prepared = manifest["files"]
            else:
                prepared = []
                seen = set()
                for op in operations:
                    path = self.path(op["path"])
                    rel = path.relative_to(self.root).as_posix()
                    if rel in seen:
                        raise VaultError("Duplicate operation path")
                    seen.add(rel)
                    before = path.read_bytes() if path.exists() else None
                    expected = op.get("expected_sha256")
                    if expected != (sha(before) if before is not None else None):
                        raise Conflict("File changed before commit: " + rel)
                    old = before.decode("utf-8-sig") if before is not None else ""
                    if "content" in op:
                        if before is not None and is_daily(path) and not restore:
                            raise VaultError("Existing daily notes require targeted edits/append")
                        new = op["content"]
                    else:
                        new = old
                        for edit in op.get("edits", []):
                            find = edit["old"]
                            if not find or new.count(find) != 1:
                                raise Conflict("Targeted edit must match exactly once: " + rel)
                            new = new.replace(find, edit["new"], 1)
                        new += op.get("append", "")
                    if not restore:
                        if rel != "10 - Resources/Templates/Manual Daily Note Template.md":
                            new = restamp(new, signer)
                        else:
                            template_fields, _ = frontmatter(new)
                            if template_fields.get("updated_by") != "human" or template_fields.get("updated") != "{{date:YYYY-MM-DD}}":
                                raise VaultError("Manual output template requires human and the date token")
                        problems = validate(new, path)
                        if problems:
                            raise VaultError(rel + ": " + "; ".join(problems))
                        if is_daily(path):
                            assert_daily_append(old, new)
                    after = new.encode("utf-8")
                    if before == after:
                        continue
                    entry = {"path": rel, "before_sha256": sha(before) if before is not None else None,
                             "after_sha256": sha(after), "before": str(len(prepared)) + ".before",
                             "after": str(len(prepared)) + ".after"}
                    prepared.append(entry)
                    directory = manifest_path.parent
                    directory.mkdir(parents=True, exist_ok=True)
                    if before is not None:
                        atomic_bytes(directory / entry["before"], before)
                    atomic_bytes(directory / entry["after"], after)
                if not prepared:
                    return {"status": "unchanged", "files": [], "transaction_id": None}
                manifest = {"version": 2, "transaction_id": txid, "root": str(self.root), "time": now().isoformat(),
                            "signer": signer, "reason": reason, "status": "prepared", "files": prepared}
                atomic_json(manifest_path, manifest)
            try:
                # Validate all expected versions before applying any member.
                for entry in prepared:
                    path = self.path(entry["path"])
                    actual = sha(path.read_bytes()) if path.exists() else None
                    if actual not in (entry["before_sha256"], entry["after_sha256"]):
                        raise Conflict("Concurrent edit detected: " + entry["path"])
                for entry in prepared:
                    path = self.path(entry["path"])
                    actual = sha(path.read_bytes()) if path.exists() else None
                    if actual == entry["after_sha256"]:
                        continue
                    if actual != entry["before_sha256"]:
                        raise Conflict("Concurrent edit detected before replace")
                    after = (manifest_path.parent / entry["after"]).read_bytes()
                    if sha(after) != entry["after_sha256"]:
                        raise VaultError("Prepared snapshot hash mismatch")
                    atomic_bytes(path, after)
                    if sha(path.read_bytes()) != entry["after_sha256"]:
                        raise Conflict("Write verification failed")
                manifest["status"] = "committed"
                manifest["completed_at"] = now().isoformat()
                atomic_json(manifest_path, manifest)
                return {"status": "committed", "transaction_id": txid, "files": prepared}
            except Exception:
                manifest["status"] = "interrupted"
                atomic_json(manifest_path, manifest)
                raise

    def restore(self, snapshot_id, relative_path, expected_sha256):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", snapshot_id):
            raise VaultError("Invalid snapshot id")
        manifest_path = self.backups / snapshot_id / "manifest.json"
        manifest = json.loads(read_text(manifest_path))
        if manifest.get("root") != str(self.root):
            raise VaultError("Snapshot belongs to another vault")
        rel = self.path(relative_path).relative_to(self.root).as_posix()
        entry = next((x for x in manifest["files"] if x["path"] == rel), None)
        if not entry or entry["before_sha256"] is None:
            raise VaultError("Snapshot has no prior version; restore never deletes notes")
        old = (manifest_path.parent / entry["before"]).read_bytes()
        if sha(old) != entry["before_sha256"]:
            raise VaultError("Snapshot hash mismatch")
        return self.commit([{"path": rel, "expected_sha256": expected_sha256, "content": old.decode("utf-8")}],
                           "human", "Explicit restore from " + snapshot_id, restore=True)


def daily_path(day):
    day = dt.date.fromisoformat(str(day)) if not isinstance(day, dt.date) else day
    return "01 - Daily Notes/" + day.strftime("%m - %B %Y/%Y-%m-%d.md")


def daily_operation(vault, day, local_time, topic, sections, signer, marker, open_next=None):
    """Construct a targeted daily append. Source marker makes retries idempotent."""
    rel = daily_path(day)
    info = vault.inspect(rel)
    old = info["text"]
    if old and marker in old:
        return None
    if not topic.strip() or any(c in topic for c in "\r\n"):
        raise VaultError("Invalid session topic")
    if any(key not in SCHEMA["daily_sections"] for key in sections):
        raise VaultError("Unknown daily section")
    number = max([int(n) for n in re.findall(r"^## Session (\d+)\b", old or "", re.M)], default=0) + 1
    newline = "\r\n" if old and "\r\n" in old else "\n"
    if old:
        index_ending = re.search(r"^## Index[^\r\n]*(\r?\n)", old, re.M)
        if index_ending:
            newline = index_ending.group(1)
    body = [f"## Session {number} — {local_time}: {topic} — `{signer}`", marker, ""]
    for heading in SCHEMA["daily_sections"]:
        body.append("### " + heading)
        entries = sections.get(heading) or ["None"]
        for entry in entries:
            if not isinstance(entry, str) or "\n" in entry or "\r" in entry:
                raise VaultError("Daily bullets must be single lines")
            body.append("- " + entry)
        body.append("")
    session = newline.join(body)
    index_line = f"- **{topic}** — {sections.get('What Got Done', ['Recorded session work.'])[0]} `({signer})`"
    if old is None:
        day_date = dt.date.fromisoformat(day)
        title = day_date.strftime("%A, %B ") + str(day_date.day) + day_date.strftime(", %Y")
        template_path = vault.root / "01 - Daily Notes" / "Daily Note Template.md"
        if not template_path.exists():
            raise VaultError("Canonical daily template is missing")
        template = read_text(template_path)
        # The template's frontmatter remains valid on disk. These explicit
        # placeholders also support the human Daily Notes UI template.
        replacements = {"{{date:dddd, MMMM D, YYYY}}": title, "{{date:YYYY-MM-DD}}": now().date().isoformat(),
                        "{{time:h:mm A}}": local_time, "{{model}}": signer}
        for token, replacement in replacements.items():
            template = template.replace(token, replacement)
        template = re.sub(r"<!--.*?-->", "", template, flags=re.S)
        fields, _ = frontmatter(template)
        # Keep template authority for schema and required body layout; remove
        # its human session stub and render the verified capture's session.
        prefix = template.split("## Index", 1)[0]
        prefix = re.sub(r"^\*\*Open for tomorrow:\*\*[^\n]*", "**Open for tomorrow:** " + (open_next or "See Active Priorities."), prefix, flags=re.M)
        content = prefix.rstrip() + "\n\n## Index\n\n" + index_line + "\n\n" + session
        return {"path": rel, "expected_sha256": None, "content": content}
    edits = [{"old": "## Index", "new": "## Index" + newline + newline + index_line}]
    if open_next:
        # Backfills must not overwrite a later recorded session's handoff.
        proposed_time = dt.datetime.strptime(local_time, "%I:%M %p").time()
        times = []
        for match in re.finditer(r"^## Session[^\n]*?(\d{1,2}:\d{2}\s*[AP]M)", old, re.M | re.I):
            try:
                times.append(dt.datetime.strptime(match.group(1).upper(), "%I:%M %p").time())
            except ValueError:
                pass
        if not times or proposed_time >= max(times):
            line = re.search(r"^\*\*Open for tomorrow:\*\*[^\r\n]*", old, re.M)
            if line:
                edits.append({"old": line.group(0), "new": "**Open for tomorrow:** " + open_next})
    return {"path": rel, "expected_sha256": info["sha256"], "edits": edits,
            "append": (newline if old.endswith(newline) else newline * 2) + session}
