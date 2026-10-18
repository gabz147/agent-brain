"""Agent adapters: one JSON manifest per agent, so a new agent is data and fixtures, never code."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil

HERE = Path(__file__).resolve().parent
ADAPTERS = HERE / "adapters"
START, END = "<!-- SHARED VAULT RULES START -->", "<!-- SHARED VAULT RULES END -->"
BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
SKILLS = ("obsidian-vault", "handoff", "source-to-vault")
# Claude and Codex keep their v1 menu numbers; the rest follow by id.
FIRST = ("claude", "codex")
SUPPORTED_STRATEGIES = ("marker-block", "rules-file")
# Lines earlier releases kept after the block. The tail now lives inside it, so an upgrade drops these.
LEGACY_TAILS = (
    "Verify Claude's runtime model from trusted metadata or this transcript's `message.model`. A Stop-hook reminder does not establish capture.",
    "Codex has no hooks: run `vaultctl.py session-brief` once for continuity, checkpoint directly, and verify the runtime model from this session's `turn_context.model` in `~/.codex/sessions/`.",
    "Codex has no hooks: run `vaultctl.py session-brief` once for continuity, checkpoint directly, and verify the runtime model from trusted metadata or this session's `turn_context.model` in `~/.codex/sessions/`.",
    "Codex has no Claude hooks. Checkpoint directly; verify the runtime model from trusted metadata or this session's `turn_context.model` in `~/.codex/sessions/`.",
)


class AdapterError(ValueError):
    pass


def boot_path():
    """BRAIN.md beside the installed controller, else the checkout's boot/BRAIN.md."""
    for path in (HERE / "BRAIN.md", HERE.parent / "boot/BRAIN.md"):
        if path.is_file():
            return path
    raise AdapterError("BRAIN.md is missing beside the controller; rerun setup")


def check(value, schema, where="manifest"):
    """Problems with value under a JSON Schema subset: type, required, properties, additionalProperties, enum, pattern, items, minItems."""
    names = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
    kinds = schema.get("type")
    if kinds:
        kinds = [kinds] if isinstance(kinds, str) else kinds
        if not any(isinstance(value, names[k]) for k in kinds):
            return [f"{where} must be {' or '.join(kinds)}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{where} must be one of {schema['enum']}"]
    problems = []
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        problems.append(f"{where} does not match {schema['pattern']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            problems.append(f"{where} needs at least {schema['minItems']} item(s)")
        for i, item in enumerate(value):
            problems += check(item, schema.get("items", {}), f"{where}[{i}]")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        problems += [f"{where}.{key} is required" for key in schema.get("required", []) if key not in value]
        if schema.get("additionalProperties") is False:
            problems += [f"{where}.{key} is not a known field" for key in value if key not in properties]
        for key, item in value.items():
            if key in properties:
                problems += check(item, properties[key], f"{where}.{key}")
    return problems


def load(directory=ADAPTERS):
    """Every manifest by id, validated; an invalid one stops setup and names its file."""
    directory = Path(directory)
    schema = json.loads((directory / "schema.json").read_text(encoding="utf-8"))
    adapters = {}
    for path in sorted(directory.glob("*.json")):
        if path.name == "schema.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise AdapterError(f"{path.name} is not valid JSON ({exc})") from exc
        problems = check(data, schema, path.stem)
        if not problems and data["id"] != path.stem:
            problems.append(f"{path.name} must declare id {path.stem!r}")
        if problems:
            raise AdapterError(f"Invalid adapter {path.name}: " + "; ".join(problems))
        adapters[data["id"]] = data
    order = [a for a in FIRST if a in adapters] + sorted(a for a in adapters if a not in FIRST)
    return {a: adapters[a] for a in order}


def expand(path, home):
    return Path(home) / path[2:] if path.startswith("~/") else Path(path)


def block_body():
    match = re.search(re.escape(START) + r"\n(.*?)\n" + re.escape(END), boot_path().read_text(encoding="utf-8"), re.S)
    if not match:
        raise AdapterError("BRAIN.md has no shared rules block")
    return match.group(1)


def render_block(adapter, body=None):
    """The canonical block for one agent: the shared rules, then that agent's tail line."""
    return f"{START}\n{body if body is not None else block_body()}\n\n{adapter['instructions']['tail']}\n{END}"


def render_file(adapter, body=None):
    return f"# Agent Brain: {adapter['display']}\n\n{render_block(adapter, body)}\n"


def merge_block(existing, adapter, body=None):
    """Existing instructions with the block replaced (or appended) and any legacy tail after it dropped."""
    if len(BLOCK.findall(existing)) > 1:
        raise AdapterError("Multiple shared boot blocks need manual reconciliation")
    block = render_block(adapter, body)
    if not BLOCK.search(existing):
        return existing.rstrip() + "\n\n" + block + "\n" if existing.strip() else render_file(adapter, body)
    merged = BLOCK.sub(lambda _: block, existing)
    head, tail = merged.split(END, 1)
    for legacy in LEGACY_TAILS:
        stripped = re.sub(r"^\s*(?:## (?:Claude|Codex) runtime\s*)?" + re.escape(legacy) + r"[ \t]*(?:\r?\n|$)", "", tail, count=1)
        if stripped != tail:
            tail = "\n\n" + stripped.lstrip("\r\n") if stripped.strip() else "\n"
            break
    return head + END + tail


def instructions_path(adapter, home):
    path = adapter["instructions"]["path"]
    return expand(path, home) if path else None


def installed_block(adapter, home):
    path = instructions_path(adapter, home)
    if path is None or not path.is_file():
        return None
    match = BLOCK.search(path.read_text(encoding="utf-8-sig"))
    return match.group() if match else None


def is_installed(adapter, home, adapters):
    """An agent participates when its instructions carry the block or a skills dir only it reads holds Brain skills."""
    if installed_block(adapter, home) is not None:
        return True
    shared = {d for other in adapters.values() if other["id"] != adapter["id"] for d in other["skills"] + other.get("legacy_skills", [])}
    return any((expand(d, home) / SKILLS[0] / "SKILL.md").exists()
               for d in adapter["skills"] + adapter.get("legacy_skills", []) if d not in shared)


def detected(adapter, home, environ=None, which=None):
    environ = os.environ if environ is None else environ
    which = which or shutil.which
    probe = adapter["detect"]
    return (any(expand(d, home).is_dir() for d in probe["dirs"]) or any(environ.get(v) for v in probe["env"])
            or any(which(b) for b in probe["binaries"]))


def skill_dirs(selected, home, adapters=None):
    """Directories that give every selected agent the skills exactly once where possible.

    A dir an earlier agent already received counts for every later agent that reads it;
    otherwise an agent gets its first listed dir. Legacy dirs that already hold Brain
    skills are refreshed in place so no stale copy lingers; they are never created."""
    adapters = adapters or load()
    chosen = []
    for name in selected:
        dirs = adapters[name]["skills"]
        if not any(d in chosen for d in dirs):
            chosen.append(dirs[0])
    for name in selected:
        for d in adapters[name].get("legacy_skills", []):
            if d not in chosen and (expand(d, home) / SKILLS[0] / "SKILL.md").exists():
                chosen.append(d)
    return [expand(d, home) for d in chosen]
