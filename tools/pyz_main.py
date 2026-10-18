"""brain.pyz: the Agent Brain release bundle (a zipapp of this repository's installable files).

  python brain.pyz setup [install.py options]   guided or scripted setup, e.g. `setup --wizard`
  python brain.pyz test                          run the bundled test suite from an extracted copy
  python brain.pyz version                       print the bundle version
  python brain.pyz <command> ...                 run the installed controller, like the `brain` launcher
"""
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile

VERSION = "{{VERSION}}"


def archive():
    return Path(__file__).resolve().parent  # a zipapp's __main__ lives at the archive root


def extract(destination):
    """Unpack every member after checking it stays inside the destination."""
    with zipfile.ZipFile(archive()) as bundle:
        for info in bundle.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in info.filename or ":" in info.filename:
                raise SystemExit(f"Refusing an unsafe bundle member: {info.filename}")
        bundle.extractall(destination)
    return Path(destination)


def installed_controller():
    value = os.environ.get("BRAIN_AUTOMATION_DIR")
    if not value:
        try:
            value = json.loads((Path.home() / ".agent-brain/config.json").read_text(encoding="utf-8-sig")).get("automation_dir")
        except (OSError, ValueError, AttributeError):
            value = None
    for candidate in [value, Path.home() / ".agent-brain/automation", Path.home() / ".claude/vault-automation"]:
        if candidate and (Path(candidate) / "vaultctl.py").is_file():
            return Path(candidate) / "vaultctl.py"
    return None


def main(argv):
    if sys.version_info < (3, 10):
        raise SystemExit("Agent Brain needs Python 3.10+: https://www.python.org/downloads/")
    command = argv[0] if argv else "help"
    if command in ("help", "-h", "--help"):
        print(__doc__)
        return 0
    if command == "version":
        print(VERSION)
        return 0
    if command in ("setup", "test"):
        with tempfile.TemporaryDirectory(prefix="agent-brain-") as tmp:
            root = extract(tmp)
            if command == "setup":
                return subprocess.call([sys.executable, str(root / "install.py"), *argv[1:]])
            return subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", str(root / "automation/tests"), "-q", *argv[1:]],
                                   cwd=str(root))
    controller = installed_controller()
    if controller is None:
        raise SystemExit("Agent Brain is not installed here yet; run: python brain.pyz setup --wizard")
    return subprocess.call([sys.executable, str(controller), *argv])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
