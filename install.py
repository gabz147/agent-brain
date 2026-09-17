"""Set up a private Obsidian Brain for Claude Code, Codex, or both."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

if sys.version_info < (3, 11):
    raise SystemExit("Install Python 3.11+ from https://www.python.org/downloads/ and rerun setup.")
import tomllib

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parent
BLOCK = re.compile(r"<!-- SHARED VAULT RULES START -->.*?<!-- SHARED VAULT RULES END -->", re.S)
SKILLS = ("obsidian-vault", "handoff", "source-to-vault")


def selected(client):
    if client not in ("claude", "codex", "both"):
        raise ValueError("Choose claude, codex, or both")
    return ("claude", "codex") if client == "both" else (client,)


def environment(home, vault):
    return {"BRAIN_VAULT_ROOT": str(vault), "BRAIN_AUTOMATION_DIR": str(home / ".claude/vault-automation"),
            "BRAIN_PYTHON": sys.executable}


def toml_bytes(data):
    """Preserve parsed settings; original comments/formatting remain in the backup."""
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
    auto = home / ".claude/vault-automation"
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
                             ("obsidian-templates.json", "templates.json")):
            add(vault / ".obsidian" / name, (REPO / "settings" / source).read_bytes())
        add(vault / ".obsidian/core-plugins.json", b'["file-explorer", "global-search", "backlink", "daily-notes", "templates", "bases"]\n')

    for path in (REPO / "automation").iterdir():
        if path.is_file() and (path.suffix in {".py", ".ps1", ".vbs", ".md", ".mjs"} or path.name == "vault-schema.json"):
            # Preserve an existing customized schema, including folder/project mappings.
            if path.name == "vault-schema.json" and (auto / path.name).exists():
                continue
            add(auto / path.name, path.read_bytes())
    add(auto / "FIRST-CHECKPOINT.md", (REPO / "FIRST-CHECKPOINT.md").read_bytes())
    if "claude" in clients:
        copy_tree(REPO / "hooks/vault", home / ".claude/hooks/vault")
    for name in clients:
        boot = "CLAUDE.md" if name == "claude" else "AGENTS.md"
        target = home / ("." + name) / boot
        text = (REPO / "boot" / boot).read_text(encoding="utf-8")
        if target.exists() and target.read_text(encoding="utf-8-sig") != text:
            existing = target.read_text(encoding="utf-8-sig")
            if len(BLOCK.findall(existing)) > 1:
                raise ValueError(f"Multiple shared boot blocks need manual reconciliation: {target}")
            block = BLOCK.search(text).group()
            text = BLOCK.sub(lambda _: block, existing) if BLOCK.search(existing) else existing.rstrip() + "\n\n" + text
            if text != existing and not replace:
                conflicts.append(str(target))
                continue
        add(target, text.encode("utf-8"))
        for skill in SKILLS:
            copy_tree(REPO / "skills" / skill, home / ("." + name) / "skills" / skill)

    if "claude" in clients:
        merge_claude(home, env, add, replace)
    if "codex" in clients:
        target = home / ".codex/config.toml"
        original = target.read_text(encoding="utf-8-sig") if target.exists() else ""
        config = tomllib.loads(original)
        policy = config.setdefault("shell_environment_policy", {})
        if not isinstance(policy, dict) or not isinstance(policy.get("set", {}), dict):
            raise ValueError("Codex shell_environment_policy and set must be tables")
        policy.setdefault("set", {}).update(env)
        if config != tomllib.loads(original):
            add(target, toml_bytes(config), merge=True)
    if conflicts:
        raise ValueError("Existing workflow files differ; review them and use --replace-workflow to back up and replace package files:\n" + "\n".join(conflicts))
    return files


def merge_claude(home, env, add, replace):
    settings_path = home / ".claude/settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8-sig")) if settings_path.exists() else {}
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        raise ValueError("Claude settings and hooks must be JSON objects")
    if not isinstance(settings.get("env", {}), dict):
        raise ValueError("Claude settings.env must be an object")
    settings.setdefault("env", {}).update(env)
    snippet = json.loads((REPO / "settings/vault-hooks.snippet.json").read_text(encoding="utf-8"))
    hooks = settings.setdefault("hooks", {})
    for event, entries in snippet["hooks"].items():
        existing = hooks.setdefault(event, [])
        if not isinstance(existing, list):
            raise ValueError(f"hooks.{event} must be an array")
        for entry in entries:
            # Replace parsed fields, never interpolate a path into serialized JSON.
            entry = json.loads(json.dumps(entry))
            for hook in entry["hooks"]:
                name = Path(hook["args"][0]).name
                interpreter = sys.executable if hook["command"] == "python" else shutil.which("node") or "node"
                hook["command"] = interpreter
                hook["args"] = [str(home / ".claude/hooks/vault" / name)]
            # Match only our adapter filenames; preserve all unrelated commands/groups.
            def matches(hook):
                return name in hook.get("command", "") or any(name in a for a in hook.get("args", []))
            matching = [h for group in existing for h in group.get("hooks", [])
                        if matches(h)]
            if matching:
                if matching != entry["hooks"]:
                    # Only replace an isolated, recognized Brain hook group. Never discard other hooks.
                    groups = [g for g in existing if any(matches(h) for h in g.get("hooks", []))]
                    if not replace or len(groups) != 1 or len(groups[0].get("hooks", [])) != 1:
                        raise ValueError(f"Existing {event} vault hook differs; review and use --replace-workflow, or merge a combined hook group manually")
                    existing[existing.index(groups[0])] = entry
            else:
                existing.append(entry)
    add(settings_path, (json.dumps(settings, indent=2, ensure_ascii=False) + "\n").encode(), merge=True)


def install(home, vault, apply=False, replace=False, client="both"):
    files = installation(home, vault, replace, client)
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
    if backup.exists():
        print("Backups: " + str(backup))
    return files


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
    names = (["node"] if "claude" in selected(client) else []) + (list(selected(client)) if include_clients else [])
    print(f"Python {sys.version.split()[0]}: {sys.executable}")
    for name in names:
        try:
            result = subprocess.run(executable(name) + ["--version"], capture_output=True, text=True, encoding="utf-8", timeout=20)
            if result.returncode:
                raise ValueError(f"{name} --version failed: {result.stderr.strip()}")
            if name == "node" and int(result.stdout.strip().lstrip("v").split(".")[0]) < 22:
                raise ValueError("Node.js 22+ is required for the Claude hook runtime")
            if name == "claude":
                version = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout)
                if not version or tuple(map(int, version.groups())) < (2, 1, 270):
                    raise ValueError("Update Claude Code to 2.1.270+ for the tested direct-execution hooks")
            print(f"OK {name}: {result.stdout.strip()}")
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            problems.append(name)
            print(f"MISSING {name}: {exc}")
    if "node" in problems:
        print("Install Node.js LTS: https://nodejs.org/en/download then reopen your terminal.")
    for name in selected(client):
        if name in problems:
            print(f"Install {name}: " + ("https://code.claude.com/docs/en/setup" if name == "claude" else "https://github.com/openai/codex#installing-and-running-codex-cli"))
    return problems


def install_client(name):
    """Run only the selected client's official native installer, after opt-in."""
    windows = os.name == "nt"
    url = ("https://claude.ai/install." if name == "claude" else "https://chatgpt.com/codex/install.") + ("ps1" if windows else "sh")
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
    paths = set()
    for name in selected(client):
        path = home / ("." + name) / ("settings.json" if name == "claude" else "config.toml")
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8-sig")
        data = json.loads(text) if name == "claude" else tomllib.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"{name} settings must be an object")
        env = data.get("env", {}) if name == "claude" else data.get("shell_environment_policy", {}).get("set", {})
        if env.get("BRAIN_VAULT_ROOT"):
            paths.add(Path(env["BRAIN_VAULT_ROOT"]).expanduser().resolve())
    if len(paths) > 1:
        raise ValueError("Selected clients use different vaults. Choose the intended one with --vault.")
    return next(iter(paths), home / "Documents/Brain")


def verify(home, vault):
    env = {k: v for k, v in os.environ.items() if not k.startswith("BRAIN_") and k not in ("VAULT_AUTOMATION_DIR", "VAULT_AUTOMATION")}
    env.update(environment(home, vault), HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8")
    for check in ("validate", "hygiene"):
        result = subprocess.run([sys.executable, str(home / ".claude/vault-automation/vaultctl.py"), check],
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
    parser.add_argument("--client", choices=("claude", "codex", "both"), default="both")
    parser.add_argument("--wizard", action="store_true", help="Choose a client and vault, check prerequisites, preview and confirm installation")
    parser.add_argument("--doctor", action="store_true", help="Check prerequisites without writing")
    parser.add_argument("--verify", action="store_true", help="Check the installed vault and workflow without reinstalling")
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    if args.wizard:
        if not sys.stdin.isatty():
            parser.error("Interactive setup needs a terminal. Use --client claude|codex|both and --apply for scripted installation.")
        print("Agent Brain: a private Obsidian vault for your terminal agent.\nObsidian should already be installed. No GitHub login is needed.")
        answer = input("Choose your agent: 1 Claude Code, 2 Codex, 3 Both [1]: ").strip() or "1"
        if answer not in ("1", "2", "3"):
            parser.error("Choose 1, 2, or 3; rerun setup.")
        args.client = {"1": "claude", "2": "codex", "3": "both"}[answer]
    if home == Path.home().resolve():
        for name, variable in (("claude", "CLAUDE_CONFIG_DIR"), ("codex", "CODEX_HOME")):
            value = os.environ.get(variable)
            if name in selected(args.client) and value and Path(value).expanduser().resolve() != home / ("." + name):
                raise ValueError(f"{variable} points to a nonstandard client directory. Use the manual INSTALL.md steps; no standard-profile files were changed.")
    vault = (args.vault or configured_vault(home, args.client)).expanduser().resolve()
    if args.wizard:
        answer = input(f"Vault folder [{vault}]: ").strip()
        if answer:
            vault = Path(answer).expanduser().resolve()
    if args.persist_env and (os.name != "nt" or home != Path.home().resolve()):
        parser.error("--persist-env requires Windows and the current user's home")
    if any(root == vault or vault in root.parents or root in vault.parents for root in (REPO, home / ".claude", home / ".codex")):
        parser.error("Vault must be separate from the checkout and client directories")
    if args.doctor:
        return 1 if doctor(args.client) else 0
    if args.verify:
        verify(home, vault)
        return 0
    if args.wizard:
        problems = doctor(args.client)
        if "node" in problems:
            return 1
        for name in problems:
            if home != Path.home().resolve():
                raise ValueError("Install missing clients separately before testing an isolated --home")
            if input(f"Install {name} using its official native installer? [y/N]: ").strip().lower() != "y":
                return 1
            install_client(name)
        if problems and doctor(args.client):
            print("Reopen your terminal to refresh PATH, then rerun this setup.")
            return 1
        print(f"\nClients: {args.client}\nVault: {vault}\nOnly three Brain skills, boot rules, writer and selected-client configuration will be installed.")
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
        print(f"Then follow the first-checkpoint prompt saved at:\n{home / '.claude/vault-automation/FIRST-CHECKPOINT.md'}")
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
