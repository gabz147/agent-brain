"""Read-only local Obsidian observations for the Brain vault. Vault writes belong to vaultctl.

Run with --help. This helper never invokes a native write, eval, or restore command.

Configuration (all optional; the defaults suit a standard install):
  BRAIN_VAULT_ROOT         vault folder (default ~/Documents/Brain, as vault_core.py)
  BRAIN_OBSIDIAN_CLI       Obsidian CLI executable (default: Obsidian.com in the Windows per-user
                           install folder, else `obsidian` on PATH)
  BRAIN_OBSIDIAN_VAULT     native vault selector (default: the vault's ID from Obsidian's own
                           obsidian.json, else the vault folder name)
  BRAIN_OBSIDIAN_TIMEOUT   seconds per native call (default 20)
Every public request verifies that the selected native vault resolves to the configured folder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
from typing import Any


# Exact native commands and fixed flags. Commands in PATH_COMMANDS also take one validated
# `path=` option. No raw command/passthrough interface.
ALLOWED = {
    "vault": {"info=path"},
    "version": set(),
    "backlinks": {"counts", "format=json"},
    "unresolved": {"verbose", "format=json"},
    "orphans": set(),
    "properties": {"counts", "format=json"},
    "history": set(),
}
PATH_COMMANDS = {"backlinks", "properties", "history"}
NEEDS_PATH = {"backlinks", "history"}
# Native failures are often printed on stdout with exit code 0.
ERROR_OUTPUT = re.compile(
    r"^(?:Error:|TypeError:|ReferenceError:|RangeError:|SyntaxError:|"
    r"Unknown command\b|Command line interface is not enabled\b|Vault not found\b)", re.I
)


class ObservationError(Exception):
    """A failed or untrustworthy CLI observation."""


def default_vault() -> Path:
    return Path(os.environ.get("BRAIN_VAULT_ROOT") or Path.home() / "Documents" / "Brain").expanduser()


def obsidian_config_dirs() -> list[Path]:
    """Where Obsidian keeps its global obsidian.json on each platform."""
    home = Path.home()
    dirs = []
    if os.environ.get("APPDATA"):
        dirs.append(Path(os.environ["APPDATA"]) / "obsidian")
    dirs.append(home / "Library" / "Application Support" / "obsidian")
    dirs.append(Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "obsidian")
    dirs.append(home / ".var" / "app" / "md.obsidian.Obsidian" / "config" / "obsidian")
    return dirs


def discover_vault_id(vault: Path, config_dirs=None) -> str | None:
    """The vault's ID in Obsidian's global config, matched by its resolved folder."""
    want = os.path.normcase(str(Path(vault).resolve()))
    for folder in (obsidian_config_dirs() if config_dirs is None else config_dirs):
        try:
            vaults = json.loads((Path(folder) / "obsidian.json").read_text(encoding="utf-8-sig")).get("vaults", {})
        except (OSError, ValueError, AttributeError):
            continue
        for vault_id, info in (vaults.items() if isinstance(vaults, dict) else ()):
            path = info.get("path") if isinstance(info, dict) else None
            if path and os.path.normcase(str(Path(path).expanduser().resolve())) == want:
                return str(vault_id)
    return None


def discover_cli() -> Path | None:
    configured = os.environ.get("BRAIN_OBSIDIAN_CLI")
    if configured:
        return Path(configured).expanduser()
    if os.environ.get("LOCALAPPDATA"):
        com = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Obsidian" / "Obsidian.com"
        if com.is_file():
            return com
    found = shutil.which("obsidian")
    return Path(found) if found else None


class Reader:
    def __init__(self, vault_path=None, vault_id=None, executable=None, timeout=None,
                 runner=subprocess.run, config_dirs=None):
        self.vault = Path(vault_path or default_vault()).resolve(strict=True)
        self.selector = (vault_id or os.environ.get("BRAIN_OBSIDIAN_VAULT")
                         or discover_vault_id(self.vault, config_dirs) or self.vault.name)
        self.executable = Path(executable) if executable else discover_cli()
        self.timeout = timeout or float(os.environ.get("BRAIN_OBSIDIAN_TIMEOUT") or 20)
        self.runner = runner

    def note(self, value: str) -> tuple[str, Path]:
        """Require an existing Markdown file strictly inside the intended vault.

        Returns the on-disk relative path (true letter case), which is what Obsidian matches."""
        if not value or any(ord(c) < 32 for c in value) or '"' in value:
            raise ObservationError("Note path is empty or contains control/quote characters.")
        portable = value.replace("\\", "/")
        parts = portable.split("/")
        if (PureWindowsPath(value).drive or portable.startswith("/")
                or any(p in {"", ".", ".."} for p in parts)
                or any(p.lower() == ".obsidian" for p in parts)
                or ":" in portable or not portable.lower().endswith(".md")):
            raise ObservationError("Use an exact vault-relative Markdown path without traversal.")
        try:
            target = (self.vault / Path(*parts)).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ObservationError(f"Cannot resolve note: {value}") from exc
        if not target.is_file() or not target.is_relative_to(self.vault):
            raise ObservationError("Note resolves outside the vault or is not a file.")
        relative = target.relative_to(self.vault)
        if any(p.lower() == ".obsidian" for p in relative.parts):
            raise ObservationError("Note resolves into Obsidian configuration.")
        return relative.as_posix(), target

    def _run(self, command: str, *options: str) -> str:
        allowed = ALLOWED.get(command)
        if allowed is None:
            raise ObservationError(f"Native command is not permitted: {command}")
        has_path = False
        for option in options:
            if option.startswith("path=") and command in PATH_COMMANDS and not has_path:
                self.note(option[5:])
                has_path = True
            elif option not in allowed:
                raise ObservationError(f"Native option is not permitted for {command}.")
        if command in NEEDS_PATH and not has_path:
            raise ObservationError(f"An explicit note path is required for {command}.")
        if self.executable is None:
            raise ObservationError("Obsidian CLI not found; install Obsidian 1.12.7+, enable it in "
                                   "Settings > General, or set BRAIN_OBSIDIAN_CLI.")
        argv = [str(self.executable), f"vault={self.selector}", command, *options]
        try:
            completed = self.runner(argv, capture_output=True, timeout=self.timeout,
                                    check=False, shell=False)
        except subprocess.TimeoutExpired as exc:
            raise ObservationError(f"{command} timed out after {self.timeout:g} seconds "
                                   "(a cold Obsidian start can take longer; retry).") from exc
        except OSError as exc:
            raise ObservationError(f"Cannot run Obsidian CLI: {exc}") from exc
        try:
            output = completed.stdout.decode("utf-8-sig")
            error = completed.stderr.decode("utf-8-sig").strip()
        except UnicodeDecodeError as exc:
            raise ObservationError(f"{command} returned invalid UTF-8.") from exc
        if completed.returncode or error or ERROR_OUTPUT.match(output.lstrip()):
            reason = error or output.strip() or f"exit {completed.returncode}"
            raise ObservationError(f"{command}: {reason[:2000]}")
        return output

    def verify_vault(self) -> None:
        native = self._run("vault", "info=path").strip()
        # A native vault selector miss can fall back to another open vault.
        if (not native or not Path(native).is_absolute()
                or os.path.normcase(str(Path(native).resolve()))
                != os.path.normcase(str(self.vault))):
            raise ObservationError(f"Vault identity mismatch: CLI returned {native!r}.")

    def _json(self, command: str, *options: str, empty: str = "", expected=list) -> Any:
        output = self._run(command, *options).strip()
        if empty and output == empty:
            return expected()
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise ObservationError(f"{command} did not return the expected JSON.") from exc
        if not isinstance(parsed, expected):
            raise ObservationError(f"{command} returned an unexpected JSON structure.")
        return parsed

    def _observe(self, command: str, *options: str) -> dict:
        try:
            return {"available": True, "output": self._run(command, *options).strip()}
        except ObservationError as exc:
            return {"available": False, "error": str(exc)}

    def _local(self, note: str) -> dict:
        _, target = self.note(note)
        data = target.read_bytes()
        return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    def execute(self, command: str, note: str | None = None) -> dict:
        if command not in {"diagnostics", "link-audit", "backlinks", "properties", "history", "preflight"}:
            raise ObservationError("Unknown helper command.")
        if command in {"backlinks", "history", "preflight"} and not note:
            raise ObservationError("An explicit note path is required.")
        # Validate the note locally, then guard every public request before reading Obsidian's cache.
        path = self.note(note)[0] if note is not None else None
        self.verify_vault()
        result = {"ok": True, "command": command, "vault": str(self.vault)}
        if path:
            result["note"] = path
        if command == "diagnostics":
            result["version"] = self._run("version").strip()
            result["selector"] = self.selector
            result["executable"] = str(self.executable)
        elif command == "link-audit":
            result["unresolved"] = self._json("unresolved", "verbose", "format=json",
                                                empty="No unresolved links found.")
            raw = self._run("orphans").strip()
            result["orphans"] = [] if raw in {"", "No orphan files found."} else raw.splitlines()
            result["scope"] = ("Whole Obsidian file-link cache, including Archive; freshness and "
                               "heading/block targets are not verified.")
        elif command == "backlinks":
            result["backlinks"] = self._json("backlinks", f"path={path}", "counts", "format=json",
                                               empty="No backlinks found.")
        elif command == "properties":
            options = (f"path={path}", "format=json") if path else ("counts", "format=json")
            result["properties"] = self._json("properties", *options, expected=dict if path else list,
                                                 empty="No frontmatter found." if path else "")
            result["scope"] = ("Property inventory; global counts include Archive and zero-count keys. "
                               "Apply the vault schema and exceptions separately.")
        elif command == "history":
            result["local_history"] = self._observe("history", f"path={path}")
            result["ok"] = result["local_history"]["available"]
        elif command == "preflight":
            before = self._local(path)
            result["local_history"] = self._observe("history", f"path={path}")
            after = self._local(path)
            result["local"] = {"before": before, "after": after, "stable": before == after}
            result["checks_complete"] = result["local_history"]["available"]
            result["ok"] = result["local"]["stable"] and result["checks_complete"]
            result["scope"] = "Local observations only, not a write lock. Preserve vaultctl hash checks."
        return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("diagnostics", "link-audit"):
        sub.add_parser(name)
    properties = sub.add_parser("properties", help="Property inventory, optionally for one note")
    properties.add_argument("note", nargs="?")
    for name in ("backlinks", "history", "preflight"):
        cmd = sub.add_parser(name)
        cmd.add_argument("note", help="Exact vault-relative Markdown path")
    args = parser.parse_args(argv)
    try:
        result = Reader().execute(args.command, getattr(args, "note", None))
    except (ObservationError, OSError, ValueError) as exc:
        result = {"ok": False, "command": args.command, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
