#!/usr/bin/env bash
# Run with bash, including the Bash 3 shipped with macOS.
set -eu
brain_python=''
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    brain_python="$candidate"
    break
  fi
done
if [ -z "$brain_python" ]; then
  echo 'Install Python 3.11+ from https://www.python.org/downloads/ (or your Linux package manager), reopen Terminal, and rerun this command.' >&2
  exit 1
fi
brain_script=$(mktemp "${TMPDIR:-/tmp}/agent-brain.XXXXXX")
trap 'rm -f "$brain_script"' EXIT
curl -fsSL https://raw.githubusercontent.com/gabz147/agent-brain/main/bootstrap.py -o "$brain_script"
"$brain_python" "$brain_script" "$@"
