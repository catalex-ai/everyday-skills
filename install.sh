#!/bin/bash
# Install a CatalEx Everyday Skill into a folder you can talk to Claude from.
#
#   ./install.sh                 # installs Drive Detox into ~/drive-detox
#   ./install.sh ~/my-folder     # installs it somewhere else
#
# Nothing outside the target folder is touched, and no existing file is
# overwritten without being named below.
set -euo pipefail

SKILL="drive-detox"
TARGET="${1:-$HOME/drive-detox}"
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$SOURCE/skills/$SKILL" ]; then
  echo "Can't find skills/$SKILL next to this script." >&2
  echo "Run it from inside the everyday-skills folder you downloaded." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is missing. Install it from https://www.python.org/downloads/" >&2
  echo "then close Terminal, open it again, and run this script once more." >&2
  exit 1
fi

echo "Installing $SKILL into $TARGET"
mkdir -p "$TARGET/.claude/skills"
rm -rf "$TARGET/.claude/skills/$SKILL"
cp -R "$SOURCE/skills/$SKILL" "$TARGET/.claude/skills/$SKILL"
find "$TARGET/.claude/skills/$SKILL" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

SETTINGS="$TARGET/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
  BACKUP="$SETTINGS.backup-$(date +%Y%m%d-%H%M%S)"
  cp "$SETTINGS" "$BACKUP"
  echo "Kept your existing settings as $(basename "$BACKUP")"
fi
cp "$SOURCE/skills/$SKILL/examples/claude-settings-readonly.json" "$SETTINGS"

echo "Checking the read-only guard is in place"
printf '%s\n' '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}' \
  | python3 "$TARGET/.claude/skills/$SKILL/hooks/readonly_guard.py" >/dev/null 2>&1 \
  && { echo "FAILED: the guard let a delete through. Stopping." >&2; exit 1; } \
  || echo "  guard blocks deletes"

printf '%s\n' '{"tool_name":"Write","tool_input":{"file_path":"/tmp/x","content":"y"}}' \
  | python3 "$TARGET/.claude/skills/$SKILL/hooks/readonly_guard.py" >/dev/null 2>&1 \
  && { echo "FAILED: the guard let a file write through. Stopping." >&2; exit 1; } \
  || echo "  guard blocks file writes"

echo
echo "Done. Two things left:"
echo
echo "  1. cd $TARGET"
echo "  2. claude"
echo
echo "Then type what you want, in plain English:"
echo "     clean up my Downloads folder"
echo "     my Drive is full, what's taking up all the space?"
echo
echo "It never deletes anything. It tells you what to delete, and you decide."
echo "Stuck? Run this for a guided check of your setup:"
echo "  python3 $TARGET/.claude/skills/$SKILL/scripts/detox.py --setup"
