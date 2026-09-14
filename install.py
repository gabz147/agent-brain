"""Preview or install the shared workflow. No downloads, model calls, or task registration."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

REPO = Path(__file__).resolve().parent
BLOCK = re.compile(r"<!-- SHARED VAULT RULES START -->.*?<!-- SHARED VAULT RULES END -->", re.S)


def installation(home, vault, replace=False):
    """Build the entire plan before writing; conflicting files require explicit replacement."""
    auto = home / ".claude/vault-automation"
    files = {}
    conflicts = []

    def add(target, data, merge=False):
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
        add(vault / ".obsidian/core-plugins.json", b'["file-explorer", "global-search", "backlink", "daily-notes", "templates"]\n')

    for path in (REPO / "automation").iterdir():
        if path.is_file() and (path.suffix in {".py", ".ps1", ".vbs", ".md"} or path.name == "vault-schema.json"):
            # Preserve an existing customized schema, including folder/project mappings.
            if path.name == "vault-schema.json" and (auto / path.name).exists():
                continue
            add(auto / path.name, path.read_bytes())
    copy_tree(REPO / "hooks/vault", home / ".claude/hooks/vault")
    for client, boot in ((".claude", "CLAUDE.md"), (".codex", "AGENTS.md")):
        target = home / client / boot
        text = (REPO / "boot" / boot).read_text(encoding="utf-8")
        if target.exists() and target.read_text(encoding="utf-8-sig") != text:
            existing = target.read_text(encoding="utf-8-sig")
            if not replace:
                conflicts.append(str(target))
                continue
            if len(BLOCK.findall(existing)) > 1:
                raise ValueError(f"Multiple shared boot blocks need manual reconciliation: {target}")
            block = BLOCK.search(text).group()
            text = BLOCK.sub(lambda _: block, existing) if BLOCK.search(existing) else existing.rstrip() + "\n\n" + text
        add(target, text.encode("utf-8"))
        copy_tree(REPO / "skills", home / client / "skills")

    settings_path = home / ".claude/settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8-sig")) if settings_path.exists() else {}
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks", {}), dict):
        raise ValueError("Claude settings and hooks must be JSON objects")
    snippet = json.loads((REPO / "settings/vault-hooks.snippet.json").read_text(encoding="utf-8"))
    hooks = settings.setdefault("hooks", {})
    for event, entries in snippet["hooks"].items():
        existing = hooks.setdefault(event, [])
        if not isinstance(existing, list):
            raise ValueError(f"hooks.{event} must be an array")
        for entry in entries:
            entry = json.loads(json.dumps(entry).replace("{{CLAUDE_DIR}}", (home / ".claude").as_posix()))
            for hook in entry["hooks"]:
                if hook["command"].startswith("python "):
                    hook["command"] = '"' + Path(sys.executable).as_posix() + '"' + hook["command"][6:]
            # Match only our adapter filenames; preserve all unrelated commands/groups.
            name = entry["hooks"][0]["command"].split("/")[-1].rstrip('"')
            matching = [h for group in existing for h in group.get("hooks", [])
                        if name in h.get("command", "")]
            if matching:
                if matching != entry["hooks"]:
                    raise ValueError(f"Existing {event} vault hook differs; merge it manually before installing")
            else:
                existing.append(entry)
    add(settings_path, (json.dumps(settings, indent=2, ensure_ascii=False) + "\n").encode(), merge=True)
    if conflicts:
        raise ValueError("Existing workflow files differ; review them and use --replace-workflow to back up and replace package files:\n" + "\n".join(conflicts))
    return files


def install(home, vault, apply=False, replace=False):
    files = installation(home, vault, replace)
    backup = home / "Documents/Brain Install Backups" / dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    for target, data in files.items():
        print(("WRITE " if apply else "PLAN  ") + str(target))
        if not apply:
            continue
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home(), help="Destination user home; also supports isolated testing")
    parser.add_argument("--vault", type=Path, help="Default: <home>/Documents/Brain")
    parser.add_argument("--apply", action="store_true", help="Write the previewed files")
    parser.add_argument("--replace-workflow", action="store_true", help="Back up and replace package files; merge boot rules, preserve real notes/state/schema")
    parser.add_argument("--persist-env", action="store_true", help="Set Windows user BRAIN paths; use only for the current user's real installation")
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    vault = (args.vault or home / "Documents/Brain").expanduser().resolve()
    if args.persist_env and (os.name != "nt" or home != Path.home().resolve()):
        parser.error("--persist-env requires Windows and the current user's home")
    if any(root == vault or vault in root.parents or root in vault.parents for root in (REPO, home / ".claude", home / ".codex")):
        parser.error("Vault must be separate from the checkout and client directories")
    install(home, vault, args.apply, args.replace_workflow)
    env = {"BRAIN_VAULT_ROOT": str(vault), "BRAIN_AUTOMATION_DIR": str(home / ".claude/vault-automation"),
           "BRAIN_PYTHON": sys.executable}
    if args.apply and args.persist_env:
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            for name, value in env.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    print(json.dumps({"environment": env, "applied": args.apply}, indent=2))
    print("Set these variables in the current shell; restart terminal/Obsidian for persisted values. Next: INSTALL.md smoke checks.")


if __name__ == "__main__":
    main()
