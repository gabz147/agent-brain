"""Build dist/brain.pyz reproducibly: the same tree and version always give the same bytes.

  python tools/build_pyz.py [--version v2.0.0] [--output dist/brain.pyz]

The bundle is a zipapp (shebang plus zip) of the installable files with tools/pyz_main.py as
__main__.py. Members are sorted, stamped 1980-01-01, stored with fixed permissions and compressed
at a fixed level, so a release's SHA256SUMS can be rebuilt and compared from a checkout.
Only git-tracked files are bundled. Line endings are normalized to LF for text, matching .gitattributes, so a Windows checkout with
autocrlf builds the same bytes as Linux CI.
"""
import argparse
import hashlib
import subprocess
from pathlib import Path
import sys
import zipfile

REPO = Path(__file__).resolve().parents[1]
# Everything setup installs, plus the docs and bootstraps the bundled test suite checks.
INCLUDE = ("install.py", "FIRST-CHECKPOINT.md", "LICENSE", "automation", "boot", "bin", "hooks", "settings", "skills", "vault",
           "README.md", "INSTALL.md", "LAPTOP-SETUP.md", "SKILL.md", "bootstrap.py", "bootstrap.sh", "bootstrap.ps1",
           "get.sh", "get.ps1", "docs/*.md", "docs/examples", "plugins", "tools")
SKIP_PARTS = {"__pycache__", "node_modules", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".pyz"}
STAMP = (1980, 1, 1, 0, 0, 0)


def members():
    """Tracked files only: ignored runtime state, logs and caches beside the sources never ship."""
    listed = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--", *INCLUDE], capture_output=True, check=True).stdout
    for rel in sorted(filter(None, listed.decode("utf-8").split("\0"))):
        item = REPO / rel
        if not item.is_file() or SKIP_PARTS & set(Path(rel).parts) or item.suffix in SKIP_SUFFIXES:
            continue
        yield rel, item


def content(path):
    data = path.read_bytes()
    if path.suffix.lower() in BINARY_SUFFIXES:
        return data
    if path.suffix.lower() in (".ps1", ".vbs", ".cmd"):
        return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return data.replace(b"\r\n", b"\n")


def build(version, output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    main = (REPO / "tools/pyz_main.py").read_text(encoding="utf-8").replace("{{VERSION}}", version)
    entries = sorted(members()) + [("__main__.py", None)]
    with output.open("wb") as handle:
        handle.write(b"#!/usr/bin/env python3\n")
        with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for name, path in entries:
                info = zipfile.ZipInfo(name, STAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o755 if name in ("bin/brain",) or name.endswith(".sh") else 0o644) << 16
                info.create_system = 3  # Unix, so the permission bits mean the same on every builder
                bundle.writestr(info, main.replace("\r\n", "\n").encode("utf-8") if path is None else content(path))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", default="dev")
    parser.add_argument("--output", default=str(REPO / "dist/brain.pyz"))
    parser.add_argument("--sums", help="Also write a SHA256SUMS manifest here")
    args = parser.parse_args(argv)
    digest = build(args.version, args.output)
    if args.sums:
        Path(args.sums).write_text(f"{digest}  {Path(args.output).name}\n", encoding="utf-8", newline="\n")
    print(f"{digest}  {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
