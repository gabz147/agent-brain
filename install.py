"""Set up a private Obsidian Brain for any terminal agent with an adapter in automation/adapters."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request

if sys.version_info < (3, 10):
    raise SystemExit("Install Python 3.10+ from https://www.python.org/downloads/ and rerun setup.")
try:
    import tomllib  # 3.11+; without it Codex settings are left alone and config.json carries the paths
except ImportError:  # pragma: no cover - exercised only on 3.10
    tomllib = None

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent
CONFIG_VERSION = 1
sys.path.insert(0, str(REPO / "automation"))
from vault_adapters import (SKILLS, SUPPORTED_STRATEGIES, detected, expand, installed_block,  # noqa: E402
                            instructions_path, is_installed, load, merge_block, render_block, render_file, skill_dirs)

ADAPTERS = load(REPO / "automation/adapters")


def selected(client, home=None):
    """Adapter ids for --client: one id, a comma list, both (claude,codex) or all (every detected agent)."""
    if client == "both":
        return ("claude", "codex")
    if client == "all":
        found = tuple(name for name, adapter in ADAPTERS.items() if detected(adapter, home or Path.home()))
        if not found:
            raise ValueError("No supported agent was detected; name one with --client (" + ", ".join(ADAPTERS) + ")")
        return found
    names = tuple(dict.fromkeys(part.strip() for part in str(client).split(",") if part.strip()))
    unknown = [name for name in names if name not in ADAPTERS]
    if not names or unknown:
        raise ValueError("Choose " + ", ".join(ADAPTERS) + ", a comma-separated list, both or all")
    for name in names:
        strategy = ADAPTERS[name]["instructions"]["strategy"]
        if strategy not in SUPPORTED_STRATEGIES:
            raise ValueError(f"{ADAPTERS[name]['display']} needs the {strategy} strategy, which this release does not install yet")
    return names


LEGACY_AUTOMATION = ".claude/vault-automation"


def automation_dir(home):
    """Where the controller lives: config.json's choice, else an existing legacy install, else the neutral home.

    State and receipts live beside the controller, so an existing install is never moved."""
    configured = read_config(home).get("automation_dir")
    if isinstance(configured, str) and configured and (Path(configured).expanduser() / "vaultctl.py").is_file():
        return Path(configured).expanduser()
    if (home / LEGACY_AUTOMATION / "vaultctl.py").is_file():
        return home / LEGACY_AUTOMATION
    return home / ".agent-brain/automation"


def environment(home, vault):
    return {"BRAIN_VAULT_ROOT": str(vault), "BRAIN_AUTOMATION_DIR": str(automation_dir(home)),
            "BRAIN_PYTHON": sys.executable}


def launcher_bytes(name, auto):
    """bin/brain (POSIX sh, path in single quotes) or bin/brain.cmd (cmd.exe), with the controller folder filled in."""
    text = (REPO / "bin" / name).read_text(encoding="utf-8").replace("\r\n", "\n")
    if name.endswith(".cmd"):
        if any(c in str(auto) for c in '"%'):
            raise ValueError(f"The controller folder contains a character cmd.exe would expand: {auto}")
        return text.replace("{{AUTOMATION_DIR}}", str(auto)).replace("\n", "\r\n").encode("utf-8")
    return text.replace("{{AUTOMATION_DIR}}", str(auto).replace("'", "'\\''")).encode("utf-8")


def sync_env(existing, env):
    """Every tier reads config.json, so Brain variables are no longer added to client settings.
    Ones an earlier release injected are kept current, so a stale value never overrides the config."""
    for key, value in env.items():
        if key in existing:
            existing[key] = value


def config_bytes(home, vault, clients, existing):
    """The neutral home's config.json: Brain paths any client or adapter can read without environment injection."""
    data = dict(existing)
    known = data.get("clients") if isinstance(data.get("clients"), list) else []
    data.update({"version": CONFIG_VERSION, "vault_root": str(vault), "automation_dir": str(automation_dir(home)),
                 "python": sys.executable, "clients": sorted({*map(str, known), *clients})})
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def read_config(home):
    path = home / ".agent-brain/config.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise ValueError(f"{path} is not valid JSON ({exc}); delete it and rerun, setup regenerates it") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object; delete it and rerun, setup regenerates it")
    return data


def installed_clients(home):
    """Agents whose Brain boot block, or Brain skills in a dir only they read, are already present under this home."""
    return [name for name, adapter in ADAPTERS.items() if is_installed(adapter, home, ADAPTERS)]


def stale_clients(home, client):
    """Installed clients left out of this selection whose copies differ from this package.

    Upgrading only one of two installed clients would leave mirrored skills and boot blocks
    unequal, which the installed hygiene check reports after every file is written."""
    chosen = selected(client)
    refreshed = set(skill_dirs(chosen, home, ADAPTERS))
    stale = []
    for name in installed_clients(home):
        if name in chosen:
            continue
        adapter = ADAPTERS[name]
        copies = [expand(d, home) for d in adapter["skills"] + adapter.get("legacy_skills", [])]
        copies = [d for d in copies if d not in refreshed and (d / SKILLS[0] / "SKILL.md").exists()]
        skills_same = all((d / skill / "SKILL.md").is_file()
                          and (d / skill / "SKILL.md").read_bytes() == (REPO / "skills" / skill / "SKILL.md").read_bytes()
                          for d in copies for skill in SKILLS)
        if not skills_same or installed_block(adapter, home) != render_block(adapter):
            stale.append(name)
    return stale


def toml_bytes(data):
    """Preserve parsed settings; original comments/formatting remain in the backup."""
    if tomllib is None:
        raise ValueError("Merging Codex config.toml needs Python 3.11+; on 3.10 config.json carries the paths and Codex settings are left alone")
    def value(v):
        if isinstance(v, dict):
            return "{" + ", ".join(json.dumps(k) + " = " + value(x) for k, x in v.items()) + "}"
        if isinstance(v, list):
            return "[" + ", ".join(value(x) for x in v) + "]"
        if isinstance(v, (dt.datetime, dt.date, dt.time)):
            return v.isoformat()
        if isinstance(v, float):
            return repr(v)
        return json.dumps(v, ensure_ascii=False)
    lines = []
    def table(obj, keys):
        if keys:
            lines.append("[" + ".".join(json.dumps(k) for k in keys) + "]")
        lines.extend(json.dumps(k) + " = " + value(v) for k, v in obj.items() if not isinstance(v, dict))
        for k, v in obj.items():
            if isinstance(v, dict):
                table(v, keys + [k])
    table(data, [])
    text = "\n".join(lines) + "\n"
    if tomllib.loads(text) != data:
        raise ValueError("Cannot preserve this Codex configuration")
    return text.encode("utf-8")


def installation(home, vault, replace=False, client="both"):
    """Build the entire plan before writing; conflicting files require explicit replacement."""
    auto = automation_dir(home)
    files = {}
    conflicts = []
    clients = selected(client)
    env = environment(home, vault)

    def add(target, data, merge=False):
        root = vault if target.is_relative_to(vault) else home
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Destination escapes its root through a link: {target}")
        if target.exists():
            if not target.is_file():
                raise ValueError(f"Expected a file: {target}")
            if target.read_bytes() == data:
                return
            if not merge and not replace:
                conflicts.append(str(target))
        files[target] = data

    def copy_tree(source, destination):
        for path in source.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                add(destination / path.relative_to(source), path.read_bytes())

    if vault.exists() and any(vault.iterdir()):
        for name in ("VAULT-INDEX.md", "10 - Resources/Vault Workflow Contract.md"):
            if not (vault / name).is_file():
                raise ValueError(f"Existing vault needs a reviewed manual merge: missing {name}")
        # Existing notes, templates and app settings are never overwritten.
    else:
        copy_tree(REPO / "vault", vault)
        for source, name in (("obsidian-daily-notes.json", "daily-notes.json"),
                             ("obsidian-templates.json", "templates.json"),
                             ("obsidian-app.json", "app.json")):
            add(vault / ".obsidian" / name, (REPO / "settings" / source).read_bytes())
        add(vault / ".obsidian/core-plugins.json", b'["file-explorer", "global-search", "backlink", "daily-notes", "templates", "bases"]\n')

    for path in (REPO / "automation").iterdir():
        if path.is_file() and (path.suffix in {".py", ".ps1", ".vbs", ".md", ".mjs"} or path.name == "vault-schema.json"):
            # Preserve an existing customized schema, including folder/project mappings.
            if path.name == "vault-schema.json" and (auto / path.name).exists():
                continue
            add(auto / path.name, path.read_bytes())
    for path in sorted((REPO / "automation/adapters").glob("*.json")):
        add(auto / "adapters" / path.name, path.read_bytes())
    add(auto / "BRAIN.md", (REPO / "boot/BRAIN.md").read_bytes())
    add(auto / "FIRST-CHECKPOINT.md", (REPO / "FIRST-CHECKPOINT.md").read_bytes())
    for name in ("brain", "brain.cmd"):
        add(home / ".agent-brain/bin" / name, launcher_bytes(name, auto))
    add(home / ".agent-brain/config.json", config_bytes(home, vault, {*clients, *installed_clients(home)}, read_config(home)), merge=True)
    for name in clients:
        adapter = ADAPTERS[name]
        hooks = adapter["hooks"]
        if hooks:
            copy_tree(REPO / "hooks/vault", expand(hooks["scripts"], home))
        if hooks and hooks["format"] == "codex-hooks-json":
            shell_log = bool((read_config(home).get("hooks") or {}).get("shell_log"))
            merge_codex_hooks(home, add, replace, adapter, shell_log)
        target = instructions_path(adapter, home)
        text = render_file(adapter)
        if target.exists():
            existing = target.read_text(encoding="utf-8-sig")
            try:
                text = merge_block(existing, adapter)
            except ValueError as exc:
                raise ValueError(f"{exc}: {target}") from exc
            if text != existing and not replace:
                conflicts.append(str(target))
                continue
        add(target, text.encode("utf-8"))
    for directory in skill_dirs(clients, home, ADAPTERS):
        for skill in SKILLS:
            copy_tree(REPO / "skills" / skill, directory / skill)

    formats = {ADAPTERS[name]["settings"]["format"]: ADAPTERS[name] for name in clients if ADAPTERS[name].get("settings")}
    if "claude-settings-json" in formats:
        merge_claude(home, env, add, replace, formats["claude-settings-json"])
    if "codex-config-toml" in formats and tomllib is not None:
        target = expand(formats["codex-config-toml"]["settings"]["path"], home)
        original = target.read_text(encoding="utf-8-sig") if target.exists() else ""
        config = tomllib.loads(original)
        policy = config.get("shell_environment_policy", {})
        if not isinstance(policy, dict) or not isinstance(policy.get("set", {}), dict):
            raise ValueError("Codex shell_environment_policy and set must be tables")
        if "set" in policy:
            sync_env(policy["set"], env)
        if config != tomllib.loads(original):
            add(target, toml_bytes(config), merge=True)
    if conflicts:
        raise ValueError("Existing workflow files differ; review them and use --replace-workflow to back up and replace package files:\n" + "\n".join(conflicts))
    return files


# Brain adapters that earlier releases installed and this release retires.
# session-end-enqueue.js only fed the removed background model-capture drain;
# stop-vault-gate.js was the Node launcher replaced by stop-vault-gate.py.
RETIRED_HOOKS = ("session-end-enqueue.js", "stop-vault-gate.js")


def prune_retired_hooks(hooks):
    """Remove only retired Brain adapter commands; keep every other hook and group."""
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            entries = group.get("hooks") if isinstance(group, dict) else None
            entries = entries if isinstance(entries, list) else []
            kept = [h for h in entries if not (isinstance(h, dict) and any(
                name in str(part) for name in RETIRED_HOOKS for part in [h.get("command", ""), *(h.get("args") or [])]))]
            if entries and not kept:
                continue
            if len(kept) != len(entries):
                group = dict(group, hooks=kept)
            kept_groups.append(group)
        if kept_groups:
            hooks[event] = kept_groups
        elif groups:
            del hooks[event]


def merge_claude(home, env, add, replace, adapter):
    settings_path = expand(adapter["settings"]["path"], home)
    scripts = expand(adapter["hooks"]["scripts"], home) if adapter.get("hooks") else None
    settings = json.loads(settings_path.read_text(encoding="utf-8-sig")) if settings_path.exists() else {}
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        raise ValueError("Claude settings and hooks must be JSON objects")
    if not isinstance(settings.get("env", {}), dict):
        raise ValueError("Claude settings.env must be an object")
    if "env" in settings:
        sync_env(settings["env"], env)
    if scripts is None:
        add(settings_path, (json.dumps(settings, indent=2, ensure_ascii=False) + "\n").encode(), merge=True)
        return
    snippet = json.loads((REPO / adapter["hooks"]["snippet"]).read_text(encoding="utf-8"))
    hooks = settings.setdefault("hooks", {})
    prune_retired_hooks(hooks)

    def render(hook):
        # Replace parsed fields, never interpolate a path into serialized JSON.
        name = Path(hook["args"][0]).name
        hook["command"] = sys.executable if hook["command"] == "python" else shutil.which(hook["command"]) or hook["command"]
        hook["args"] = [str(scripts / name)]
        return name
    merge_hook_groups(hooks, snippet["hooks"], render, replace)
    add(settings_path, (json.dumps(settings, indent=2, ensure_ascii=False) + "\n").encode(), merge=True)


def shell_command(parts):
    """One hook command line. Codex runs it with `$SHELL -lc` on POSIX and `cmd.exe /C "<line>"` on Windows,
    where quoting keeps spaces and metacharacters literal but %VAR% would still expand, so that is refused."""
    if os.name != "nt":
        return shlex.join(parts)
    for part in parts:
        if any(c in part for c in '"%'):
            raise ValueError(f"Hook path contains a character cmd.exe would expand ({part}); install the Codex hooks by hand")
    return " ".join(f'"{part}"' for part in parts)


def merge_codex_hooks(home, add, replace, adapter, shell_log=False):
    """Agent Brain's Codex hooks merged into hooks.json, keeping every unrelated hook."""
    target = expand(adapter["hooks"]["path"], home)
    scripts = expand(adapter["hooks"]["scripts"], home)
    data = json.loads(target.read_text(encoding="utf-8-sig")) if target.exists() else {}
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise ValueError(f"{target} and its hooks must be JSON objects")
    snippet = json.loads((REPO / adapter["hooks"]["snippet"]).read_text(encoding="utf-8"))["hooks"]
    if shell_log:
        for group in snippet.get("PostToolUse", []):
            group["matcher"] = group.get("matcher", "") + "|Bash"

    def render(hook):
        name = hook.pop("script")
        hook["command"] = shell_command([sys.executable, str(scripts / name), *hook.pop("args", [])])
        return name
    merge_hook_groups(data.setdefault("hooks", {}), snippet, render, replace)
    add(target, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode(), merge=True)


def merge_hook_groups(hooks, snippet, render, replace):
    """Add each snippet group, or replace an isolated group holding our script; never discard another hook."""
    for event, entries in snippet.items():
        existing = hooks.setdefault(event, [])
        if not isinstance(existing, list):
            raise ValueError(f"hooks.{event} must be an array")
        for entry in entries:
            entry = json.loads(json.dumps(entry))
            for hook in entry["hooks"]:
                name = render(hook)
            # Match only our adapter filenames; preserve all unrelated commands/groups.
            def matches(hook):
                return isinstance(hook, dict) and (name in str(hook.get("command", ""))
                                                   or any(isinstance(a, str) and name in a for a in (hook.get("args") or [])))

            def entries_of(group):
                hooks_list = group.get("hooks") if isinstance(group, dict) else None
                return hooks_list if isinstance(hooks_list, list) else []
            matching = [h for group in existing for h in entries_of(group) if matches(h)]
            if matching:
                if matching != entry["hooks"]:
                    # Only replace an isolated, recognized Brain hook group. Never discard other hooks.
                    groups = [g for g in existing if any(matches(h) for h in entries_of(g))]
                    if not replace or len(groups) != 1 or len(groups[0].get("hooks", [])) != 1:
                        raise ValueError(f"Existing {event} vault hook differs; review and use --replace-workflow, or merge a combined hook group manually")
                    existing[existing.index(groups[0])] = entry
            else:
                existing.append(entry)


def install(home, vault, apply=False, replace=False, client="both"):
    files = installation(home, vault, replace, client)
    migration = timestamp_migration(vault)
    if migration:
        print("PLAN  Update the contract's legacy timestamp schema rule through the shared writer: " + migration["path"])
    before = {target: target.read_bytes() if target.exists() else None for target in files}
    backup = home / "Documents/Brain Install Backups" / dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    for target, data in files.items():
        print(("WRITE " if apply else "PLAN  ") + str(target))
        if not apply:
            continue
        current = target.read_bytes() if target.exists() else None
        if current != before[target]:
            raise ValueError(f"Concurrent edit detected; inspect and rerun: {target}")
        if target.exists():
            saved = backup / str(len(list(backup.glob("*.bak")))).zfill(4)
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved.with_suffix(".bak"))
            with (backup / "manifest.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"target": str(target), "backup": saved.with_suffix(".bak").name}) + "\n")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            handle.write(data)
            temporary = Path(handle.name)
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        if target.read_bytes() != data:
            raise OSError(f"Read-back failed: {target}")
        if target.name == "brain" and target.parent.name == "bin" and os.name != "nt":
            target.chmod(0o755)  # the POSIX launcher; NamedTemporaryFile creates 0600
    if backup.exists():
        print("Backups: " + str(backup))
    if apply and migration:
        auto = automation_dir(home)
        with tempfile.TemporaryDirectory(prefix="brain-migration-") as tmp:
            payload = Path(tmp) / "migration.json"
            payload.write_text(json.dumps({"operations": [migration]}), encoding="utf-8")
            result = subprocess.run([sys.executable, str(auto / "vaultctl.py"),
                                     "--vault", str(vault), "--state", str(auto / "state-v2"),
                                     "--backups", str(vault.parent / (vault.name + " Backups") / "versions"),
                                     "commit", "--model", "automation", "--reason", "Upgrade the write timestamp schema rule",
                                     "--input", str(payload)], capture_output=True, text=True, encoding="utf-8", timeout=60)
            if result.returncode:
                raise ValueError("Timestamp schema migration needs review: " + result.stdout + result.stderr)
            report = json.loads(result.stdout)
            if report.get("status") != "committed" or not report.get("files"):
                raise ValueError("Timestamp schema migration did not verify a write")
            print("OK contract timestamp rule migrated; snapshot: " + report["transaction_id"])
    return files


def timestamp_migration(vault):
    relative = "10 - Resources/Vault Workflow Contract.md"
    path = vault / relative
    if not path.exists():
        return None
    if not path.resolve().is_relative_to(vault.resolve()):
        raise ValueError("Contract escapes the vault through a link")
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    old_rules = ("- Updated: an actual calendar date in `YYYY-MM-DD`, taken from the system clock at the write.",
                 "- Updated: actual local write time in `YYYY-MM-DDTHH:mm:ss+/-HH:mm`; legacy `YYYY-MM-DD` dates remain valid. The writer uses the system clock and timezone.")
    block = re.search(r"<!-- VAULT SCHEMA START -->.*?<!-- VAULT SCHEMA END -->", text, re.S)
    old = next((rule for rule in old_rules if block and rule in block.group() and text.count(rule) == 1), None)
    if old is None:
        return None  # Custom wording requires review, not a guessed rewrite.
    new = "- Updated: readable local write time, for example `September 23, 2026 at 6:20:14 AM (UTC-06:00)`; legacy ISO timestamps and `YYYY-MM-DD` dates remain valid. The writer uses the system clock and timezone."
    return {"path": relative, "expected_sha256": hashlib.sha256(raw).hexdigest(),
            "edits": [{"old": old, "new": new}]}


def executable(name):
    found = shutil.which(name)
    if not found:
        # Native vendor installers may have just added this directory to future shells.
        directory = Path.home() / ".local/bin"
        if name == "codex":
            if os.name == "nt":
                directory = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Programs/OpenAI/Codex/bin"
            directory = Path(os.environ.get("CODEX_INSTALL_DIR") or directory)
        candidate = directory / (name + (".exe" if os.name == "nt" else ""))
        if candidate.is_file():
            found = str(candidate)
    if not found:
        raise ValueError(f"{name} is not installed or is missing from PATH")
    if Path(found).suffix.lower() == ".cmd" and name in ("claude", "codex"):
        package = Path(found).parent / "node_modules" / ("@openai/codex" if name == "codex" else "@anthropic-ai/claude-code")
        entry = json.loads((package / "package.json").read_text(encoding="utf-8")).get("bin")
        entry = entry.get(name) if isinstance(entry, dict) else entry
        if not isinstance(entry, str):
            raise ValueError(f"Unrecognized {name} npm launcher; install the official CLI")
        script = (package / entry).resolve()
        if not script.is_relative_to(package.resolve()) or not script.is_file():
            raise ValueError(f"Invalid {name} package executable")
        return [executable("node")[0], str(script)] if script.suffix in (".js", ".mjs", ".cjs") else [str(script)]
    return [found]


def doctor(client, include_clients=True):
    problems = []
    names = list(selected(client)) if include_clients else []
    print(f"Python {sys.version.split()[0]}: {sys.executable}")
    for name in names:
        adapter = ADAPTERS[name]
        try:
            binaries = adapter["detect"]["binaries"]
            found = None
            for binary in binaries:
                try:
                    found = executable(binary)
                    break
                except ValueError:
                    continue
            if found is None:
                raise ValueError(f"{' or '.join(binaries) or name} is not installed or is missing from PATH")
            result = subprocess.run(found + ["--version"], capture_output=True, text=True, encoding="utf-8", timeout=20)
            if result.returncode:
                raise ValueError(f"{name} --version failed: {result.stderr.strip()}")
            floor = adapter.get("min_version")
            if floor:
                version = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
                if not version or tuple(map(int, version.groups())) < tuple(map(int, floor.split("."))):
                    raise ValueError(f"Update {adapter['display']} to {floor}+, the tested minimum for its Brain hooks")
            print(f"OK {name}: {result.stdout.strip()}")
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            problems.append(name)
            print(f"MISSING {name}: {exc}")
    for name in names:
        if name in problems:
            print(f"Install {ADAPTERS[name]['display']}: {ADAPTERS[name].get('docs', 'see its official documentation')}")
    return problems


def install_client(name):
    """Run only the selected client's official native installer, after opt-in."""
    windows = os.name == "nt"
    url = ADAPTERS[name]["install"]["windows" if windows else "posix"]
    print(f"Running the official {name} installer from {url}")
    with tempfile.TemporaryDirectory(prefix="brain-cli-") as temporary:
        script = Path(temporary) / ("install.ps1" if windows else "install.sh")
        request = urllib.request.Request(url, headers={"User-Agent": "agent-brain-setup"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("Unexpectedly large client installer")
        script.write_bytes(data)
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)] if windows else ["bash" if name == "claude" else "sh", str(script)]
        # A Python child of PowerShell 7 otherwise passes incompatible PS7 modules to 5.1.
        env = {k: v for k, v in os.environ.items() if not (windows and k.upper() == "PSMODULEPATH")}
        subprocess.run(command, check=True, env=env)


def configured_vault(home, client):
    """The vault config.json and every installed client already agree on, so a newly added client joins it."""
    paths = set()
    root = read_config(home).get("vault_root")
    if isinstance(root, str) and root:
        paths.add(Path(root).expanduser().resolve())
    for name, adapter in ADAPTERS.items():
        settings = adapter.get("settings")
        if not settings:
            continue
        path, toml = expand(settings["path"], home), settings["format"] == "codex-config-toml"
        if not path.exists() or (toml and tomllib is None):
            continue
        text = path.read_text(encoding="utf-8-sig")
        data = tomllib.loads(text) if toml else json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"{name} settings must be an object")
        env = ((data.get("shell_environment_policy") or {}).get("set") or {}) if toml else (data.get("env") or {})
        if isinstance(env, dict) and isinstance(env.get("BRAIN_VAULT_ROOT"), str) and env["BRAIN_VAULT_ROOT"]:
            paths.add(Path(env["BRAIN_VAULT_ROOT"]).expanduser().resolve())
    if len(paths) > 1:
        raise ValueError("config.json and the installed clients point at different vaults. Choose the intended one with --vault.")
    return next(iter(paths), home / "Documents/Brain")


def verify(home, vault):
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_") and k not in ("VAULT_AUTOMATION_DIR", "VAULT_AUTOMATION")}
    env.update(environment(home, vault), HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8")
    for check in ("validate", "hygiene"):
        result = subprocess.run([sys.executable, str(automation_dir(home) / "vaultctl.py"), check],
                                capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        if result.returncode:
            raise ValueError(f"Installed {check} failed: {result.stdout}\n{result.stderr}")
        report = json.loads(result.stdout)
        if report.get("issues") or report.get("outcome") not in ("valid", "verified"):
            raise ValueError(f"Installed {check} needs review: {result.stdout}")
        print(f"OK installed {check}: {report['outcome']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home(), help="Destination user home; also supports isolated testing")
    parser.add_argument("--vault", type=Path, help="Default: <home>/Documents/Brain")
    parser.add_argument("--apply", action="store_true", help="Write the previewed files")
    parser.add_argument("--replace-workflow", action="store_true", help="Back up and replace package files; merge boot rules, preserve real notes/state/schema")
    parser.add_argument("--persist-env", action="store_true", help="Set Windows user BRAIN paths; use only for the current user's real installation")
    parser.add_argument("--client", default="both", help="Agent id (" + ", ".join(ADAPTERS) + "), a comma list, both (claude,codex) or all detected")
    parser.add_argument("--wizard", action="store_true", help="Choose agents and a vault, check prerequisites, preview and confirm installation")
    parser.add_argument("--render", metavar="AGENT", help="Print the instructions file this release installs for one agent, for a manual merge; writes nothing")
    parser.add_argument("--doctor", action="store_true", help="Check prerequisites without writing")
    parser.add_argument("--verify", action="store_true", help="Check the installed vault and workflow without reinstalling")
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    if args.render:
        if args.render not in ADAPTERS:
            parser.error("Unknown agent; choose " + ", ".join(ADAPTERS))
        sys.stdout.write(render_file(ADAPTERS[args.render]))
        return 0
    if args.wizard:
        if not sys.stdin.isatty():
            parser.error("Interactive setup needs a terminal. Use --client <agent>[,<agent>] and --apply for scripted installation.")
        print("Agent Brain: a private Obsidian vault for your terminal agent.\nObsidian should already be installed. No GitHub login is needed.")
        names = list(ADAPTERS)
        present = installed_clients(home) or [n for n in names if detected(ADAPTERS[n], home)] or ["claude"]
        default = ",".join(str(names.index(n) + 1) for n in present)
        menu = ", ".join(f"{i} {ADAPTERS[n]['display']}" for i, n in enumerate(names, 1))
        answer = input(f"Choose your agents ({menu}; comma-separate several) [{default}]: ").strip() or default
        picks = [part.strip() for part in answer.split(",") if part.strip()]
        try:
            args.client = ",".join(names[int(p) - 1] if p.isdigit() and 0 < int(p) <= len(names) else p for p in picks)
            selected(args.client, home)
        except ValueError as exc:
            parser.error(f"{exc}; rerun setup.")
    args.client = ",".join(selected(args.client, home))
    if home == Path.home().resolve():
        for name in selected(args.client):
            adapter = ADAPTERS[name]
            variable = adapter.get("home_env")
            value = os.environ.get(variable) if variable else None
            if value and Path(value).expanduser().resolve() != expand(adapter["home_dir"], home):
                raise ValueError(f"{variable} points to a nonstandard client directory. Use the manual steps in docs/setup.md; no standard-profile files were changed.")
    vault = (args.vault or configured_vault(home, args.client)).expanduser().resolve()
    if args.wizard:
        answer = input(f"Vault folder [{vault}]: ").strip()
        if answer:
            vault = Path(answer).expanduser().resolve()
    if args.persist_env and (os.name != "nt" or home != Path.home().resolve()):
        parser.error("--persist-env requires Windows and the current user's home")
    roots = [REPO, home / ".agent-brain", home / ".agents", *(expand(a["home_dir"], home) for a in ADAPTERS.values() if a.get("home_dir"))]
    if any(root == vault or vault in root.parents or root in vault.parents for root in roots):
        parser.error("Vault must be separate from the checkout and client directories")
    if args.doctor:
        return 1 if doctor(args.client) else 0
    if args.verify:
        verify(home, vault)
        return 0
    stale = stale_clients(home, args.client)
    if stale:
        together = [name for name in ADAPTERS if name in selected(args.client) or name in stale]
        together = "both" if together == ["claude", "codex"] else ",".join(together)
        raise ValueError(f"{' and '.join(stale)} already has an older Brain release installed under this home; "
                         f"rerun with --client {together} so every agent stays identical, or remove that agent's copies first")
    if args.wizard:
        problems = doctor(args.client)
        for name in problems:
            if home != Path.home().resolve():
                raise ValueError("Install missing clients separately before testing an isolated --home")
            if not ADAPTERS[name].get("install"):
                print(f"Install {ADAPTERS[name]['display']} from {ADAPTERS[name].get('docs', 'its official documentation')}, then rerun setup.")
                return 1
            if input(f"Install {name} using its official native installer? [y/N]: ").strip().lower() != "y":
                return 1
            install_client(name)
        if problems and doctor(args.client):
            print("Reopen your terminal to refresh PATH, then rerun this setup.")
            return 1
        print(f"\nAgents: {args.client}\nVault: {vault}\nOnly three Brain skills, boot rules, writer and selected-agent configuration will be installed.")
        try:
            install(home, vault, client=args.client)
        except ValueError as exc:
            if "Existing workflow files differ" not in str(exc) and "Existing " not in str(exc):
                raise
            print(exc)
            if input("Back up and update these workflow files? Existing notes and unrelated settings will be kept. [y/N]: ").strip().lower() != "y":
                return 1
            args.replace_workflow = True
            install(home, vault, replace=True, client=args.client)
        if input("Apply this installation? [y/N]: ").strip().lower() != "y":
            return 0
        args.apply = True
    install(home, vault, args.apply, args.replace_workflow, args.client)
    env = environment(home, vault)
    if args.apply and args.persist_env:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            for name, value in env.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    print(json.dumps({"environment": env, "applied": args.apply}, indent=2))
    if args.apply:
        verify(home, vault)
        print(f"\nBrain files verified. Open this folder as a vault in Obsidian:\n{vault}")
        print("Restart each selected CLI, sign in, and approve its normal hook/access prompts.")
        if any((ADAPTERS[name]["hooks"] or {}).get("format") == "codex-hooks-json" for name in selected(args.client)):
            print("Codex: open /hooks in a new session and trust the three Agent Brain hooks; until then they are skipped.")
        print(f"Then follow the first-checkpoint prompt saved at:\n{automation_dir(home) / 'FIRST-CHECKPOINT.md'}")
        print(f"Optional: add {home / '.agent-brain/bin'} to PATH to run controller commands as `brain <command>`.")
        print("Online guide: https://github.com/gabz147/agent-brain/blob/main/FIRST-CHECKPOINT.md")
        print("Live agent behavior and Obsidian UI still need that check; file installation cannot certify them.")
    else:
        print("Preview only. Add --apply to install, or use --wizard for guided setup.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError, EOFError) as exc:
        print(f"Setup stopped: {exc}", file=sys.stderr)
        sys.exit(1)
