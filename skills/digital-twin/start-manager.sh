#!/bin/sh
set -eu
command -v claude >/dev/null 2>&1 || { echo "Claude Code isn't installed on this computer. Install it, then run this again." >&2; exit 2; }
package=$(cd -P "$(dirname "$0")" && pwd)
cd -P "$package/manager-agent"
exec claude --strict-mcp-config --mcp-config .mcp.json "$@"
