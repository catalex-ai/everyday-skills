#!/bin/sh
set -eu
case "${1:-}" in patient|doctor) role=$1 ;; *) echo "Usage: $0 patient|doctor [codex|claude]" >&2; exit 2 ;; esac
[ "$#" -le 2 ] || exit 2
cd -P "$(dirname "$0")/$role-agent"
case "${2:-codex}" in
  codex) export CODEX_HOME="$PWD/.codex"; exec codex --no-daemon --strict-config --dangerously-bypass-hook-trust ;;
  claude) exec claude --restricted --tools Skill --strict-mcp-config --mcp-config .mcp.json --setting-sources "" --plugin-dir .claude --append-system-prompt-file AGENTS.md --settings .claude/settings.json --permission-mode dontAsk --no-chrome ;;
  *) echo "Choose codex or claude." >&2; exit 2 ;;
esac
