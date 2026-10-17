#!/bin/sh
set -eu
case "${1:-}" in patient|doctor) role=$1 ;; *) echo "Usage: $0 patient|doctor" >&2; exit 2 ;; esac
[ "$#" -le 2 ] || exit 2
[ "${2:-claude}" = claude ] || { echo "The clinic assistants run only on Claude Code with Haiku." >&2; exit 2; }
command -v claude >/dev/null 2>&1 || { echo "Claude Code isn't installed on this computer. Install it, then open the assistant again." >&2; exit 2; }
package=$(cd -P "$(dirname "$0")" && pwd)
# Patients see clinic changes before the chat starts, independent of the model.
[ "$role" = patient ] && python3 "$package/tools/notices.py" || true
cd -P "$package/$role-agent"
# Haiku only: pin the model, drop any model override in the environment, and point
# the other model names at Haiku so /model's Default, Opus or Sonnet stay on Haiku.
haiku=claude-haiku-5-5
exec env -u ANTHROPIC_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL=$haiku ANTHROPIC_DEFAULT_SONNET_MODEL=$haiku ANTHROPIC_DEFAULT_HAIKU_MODEL=$haiku \
  claude --model haiku --restricted --tools Skill --strict-mcp-config --mcp-config .mcp.json --setting-sources "" --plugin-dir .claude --append-system-prompt-file AGENTS.md --settings .claude/settings.json --permission-mode dontAsk --no-chrome
