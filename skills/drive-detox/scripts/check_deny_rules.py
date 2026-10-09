#!/usr/bin/env python3
"""Check that a Drive MCP server's write tools are denied in Claude Code settings.

Run this before authenticating a Drive connection, not after. It reads settings
files and prints what to add; it changes nothing.

Exit codes: 0 every write tool is denied, 1 something is missing, 2 bad usage.
"""
import argparse
import json
import sys
from pathlib import Path

# Google's Drive MCP server exposes exactly these two write tools, and no delete tool.
WRITE_TOOLS = ("create_file", "copy_file")
SETTINGS_PATHS = (
    Path(".claude/settings.json"),
    Path(".claude/settings.local.json"),
    Path.home() / ".claude" / "settings.json",
)


def normalize_server_name(raw):
    """Derive the server part of an MCP tool name from the display name.

    Observed live tool names keep the server's case and its dashes, and turn
    spaces and dots into underscores: "claude.ai Claude Docs" becomes
    "claude_ai_Claude_Docs", and the plugin server "claude-mem:mcp-search"
    keeps its dashes.
    """
    return raw.strip().replace(" ", "_").replace(".", "_").replace(":", "_")


def load_deny_rules(paths):
    """Collect deny rules across settings files. Returns (rules, files_read, problems)."""
    rules, read, problems = set(), [], []
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{path}: cannot read ({exc})")
            continue
        read.append(path)
        permissions = data.get("permissions")
        if isinstance(permissions, dict):
            deny = permissions.get("deny")
            if isinstance(deny, list):
                rules.update(rule for rule in deny if isinstance(rule, str))
    return rules, read, problems


def missing_rules(server, rules):
    """Which write tools are not covered. A whole-server deny covers all of them."""
    prefix = f"mcp__{server}"
    if prefix in rules or f"{prefix}__*" in rules:
        return []
    return [f"{prefix}__{tool}" for tool in WRITE_TOOLS
            if f"{prefix}__{tool}" not in rules]


def case_only_mismatches(needed, rules):
    """Rules that differ from a needed rule only by case, which will not match."""
    lowered = {rule.lower(): rule for rule in rules}
    return {rule: lowered[rule.lower()] for rule in needed if rule.lower() in lowered}


def suggestion(needed):
    return json.dumps({"permissions": {"deny": needed}}, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True,
                        help="MCP server name as 'claude mcp list' prints it")
    parser.add_argument("--settings", type=Path, action="append",
                        help="settings file to check; repeatable. Defaults to the usual three")
    args = parser.parse_args()

    server = normalize_server_name(args.server)
    if not server:
        parser.error("--server cannot be empty")
    paths = args.settings or list(SETTINGS_PATHS)
    rules, read, problems = load_deny_rules(paths)

    for problem in problems:
        print(f"WARNING: {problem}", file=sys.stderr)
    if read:
        print("Settings read:")
        for path in read:
            print(f"  {path}")
    else:
        print("No settings file found in:")
        for path in paths:
            print(f"  {path}")

    needed = missing_rules(server, rules)
    if not needed:
        print(f"\nPASS: every write tool of '{server}' is denied.")
        print("A denied tool cannot be called at all, not even with your approval.")
        return 0

    print(f"\nFAIL: these write tools of '{server}' are not denied:")
    for rule in needed:
        print(f"  {rule}")
    near = case_only_mismatches(needed, rules)
    if near:
        print("\nThese existing rules differ only by case, so they will not match:")
        for wanted, found in near.items():
            print(f"  found {found}\n  need  {wanted}")
    print("\nAdd this to .claude/settings.json in the project you audit from:")
    print(suggestion(needed))
    print("\nIf the server name is wrong the rule silently does nothing, so check it")
    print("against `claude mcp list` before trusting a pass.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
