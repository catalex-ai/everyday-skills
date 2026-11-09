#!/bin/sh
# Set up the Digital Twin on this computer. Safe to run again.
#
#   ./setup.sh                      # brain in ~/.twin/brain
#   TWIN_HOME=~/my-brain ./setup.sh # brain somewhere else
#
# It only sets up the data store and the tools. It adds no restrictions: run
# `claude` inside manager-agent/ or twin-agent/ and each loads its own MCP
# server, with that server's tools pre-approved. Whatever runs the agents (for
# example a relay app) decides which tools they may use.
#
# Everything stays local: a Python environment in .venv next to this file, and
# the brain folder. The only download is the pinned Python packages and a small
# search model (about 30 MB), once.
set -eu

package=$(cd -P "$(dirname "$0")" && pwd)
brain="${TWIN_HOME:-$HOME/.twin/brain}"
cd "$package"

say() { printf '%s\n' "$*"; }
fail() { printf '%s\n' "$*" >&2; exit 1; }

# 1. Python 3.11 or newer.
py=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    py=$(command -v "$c"); break
  fi
done
[ -n "$py" ] || fail "The Digital Twin needs Python 3.11 or newer. Install it from https://www.python.org/downloads/ and run ./setup.sh again."

# 2. Environment and pinned packages.
if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c 'import mcp, model2vec, yaml' 2>/dev/null; then
  say "Installing the Digital Twin's tools (one time)..."
  [ -x .venv/bin/python ] || "$py" -m venv .venv
  .venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt \
    || fail "Couldn't install the Python packages. Check the internet connection and run ./setup.sh again."
fi

# 3. Search model, fetched once and cached.
.venv/bin/python -c '
import os
from model2vec import StaticModel
StaticModel.from_pretrained(os.environ.get("TWIN_EMBED_MODEL", "minishlab/potion-base-8M"))
' >/dev/null 2>&1 || say "Note: the search model didn't download. Search still works by keywords, and the model is fetched the next time it is needed."

# 4. The brain. Never inside this folder.
case "$brain" in "$package"*) fail "Keep the brain outside the skill folder. Set TWIN_HOME to another folder.";; esac
TWIN_HOME="$brain" PYTHONPATH="$package" .venv/bin/python -m brainkit.cli init >/dev/null
TWIN_HOME="$brain" PYTHONPATH="$package" .venv/bin/python -m brainkit.cli status >/dev/null \
  || fail "The brain didn't start. Run ./setup.sh again; if it keeps failing, open an issue."

# 5. Claude Code.
if ! command -v claude >/dev/null 2>&1; then
  say "Ready, except Claude Code isn't installed. Install it from https://claude.com/claude-code."
  exit 0
fi

say "Digital Twin is ready. Your brain is in $brain."
say "  cd $package/manager-agent && claude   the Twin Manager (you): add your CV, answer questions, fix mistakes"
say "  cd $package/twin-agent && claude      the Twin (other people): answers as you from what you allowed"
say "Each folder loads its own tools. Use the same TWIN_HOME if you changed it."
