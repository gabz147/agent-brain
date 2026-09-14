"""Download one public repository revision and start guided Brain setup. No Git required."""
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

if sys.version_info < (3, 11):
    raise SystemExit("Install Python 3.11+ from https://www.python.org/downloads/ and rerun setup.")


def download(url, maximum):
    request = urllib.request.Request(url, headers={"User-Agent": "agent-brain-setup"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Download exceeds the setup size limit")
    return data


def unpack(data, destination):
    """Reject traversal, symlinks, duplicate targets and decompression bombs before writes."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(e.file_size for e in entries) > 50_000_000:
            raise ValueError("Archive exceeds the setup size limit")
        targets = set()
        roots = set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in entry.filename
                    or ":" in entry.filename or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError("Unsafe archive member")
            if not path.parts:
                raise ValueError("Empty archive member")
            roots.add(path.parts[0])
            key = str(path).casefold()
            if key in targets:
                raise ValueError("Duplicate archive member")
            targets.add(key)
        if len(roots) != 1:
            raise ValueError("Expected one repository root")
        root_name = next(iter(roots))
        if not any(e.filename == root_name + "/install.py" and not e.is_dir() for e in entries):
            raise ValueError("Download has no Brain installer")
        archive.extractall(destination)
    root = destination / roots.pop()
    if not (root / "install.py").is_file():
        raise ValueError("Download has no Brain installer")
    return root


def main():
    # Resolve main once, then fetch that immutable commit instead of mixing revisions.
    sha = json.loads(download("https://api.github.com/repos/gabz147/agent-brain/commits/main", 2_000_000))["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Invalid GitHub revision")
    print(f"Downloading public agent-brain revision {sha}", flush=True)
    data = download(f"https://codeload.github.com/gabz147/agent-brain/zip/{sha}", 25_000_000)
    # The installed runtime is independent of this download; no checkout or personal data sync.
    with tempfile.TemporaryDirectory(prefix="agent-brain-") as temporary:
        root = unpack(data, Path(temporary))
        return subprocess.run([sys.executable, str(root / "install.py"), *(sys.argv[1:] or ["--wizard"])], cwd=root).returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        print(f"Download/setup failed: {exc}\nCheck your connection and retry, or download the public repository ZIP from GitHub.", file=sys.stderr)
        sys.exit(1)
