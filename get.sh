#!/usr/bin/env bash
# Agent Brain v2 setup: download the pinned release bundle, check it against the release's
# SHA256SUMS, then run guided setup. Run with bash (including macOS's Bash 3):
#   bash <(curl -fsSL https://raw.githubusercontent.com/gabz147/agent-brain/main/get.sh)
# The checksum proves the download is intact, not who published it: both files come from the
# same GitHub release. Set AGENT_BRAIN_VERSION to pick another release tag.
set -eu
version="${AGENT_BRAIN_VERSION:-v2.0.0}"
base="https://github.com/gabz147/agent-brain/releases/download/$version"
brain_python=''
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    brain_python="$candidate"
    break
  fi
done
if [ -z "$brain_python" ]; then
  echo 'Install Python 3.10+ from https://www.python.org/downloads/ (or your Linux package manager), reopen Terminal, and rerun this command.' >&2
  exit 1
fi
brain_tmp=$(mktemp -d "${TMPDIR:-/tmp}/agent-brain.XXXXXX")
trap 'rm -rf "$brain_tmp"' EXIT
curl -fsSL "$base/brain.pyz" -o "$brain_tmp/brain.pyz"
curl -fsSL "$base/SHA256SUMS" -o "$brain_tmp/SHA256SUMS"
expected=$(awk '$2 == "brain.pyz" || $2 == "*brain.pyz" { print $1 }' "$brain_tmp/SHA256SUMS")
if command -v sha256sum >/dev/null 2>&1; then
  actual=$(sha256sum "$brain_tmp/brain.pyz" | awk '{ print $1 }')
else
  actual=$(shasum -a 256 "$brain_tmp/brain.pyz" | awk '{ print $1 }')
fi
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
  echo "brain.pyz does not match the SHA-256 in $version's SHA256SUMS; nothing was installed." >&2
  exit 1
fi
if [ "$#" -eq 0 ]; then
  set -- --wizard
fi
"$brain_python" "$brain_tmp/brain.pyz" setup "$@"
