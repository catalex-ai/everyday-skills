#!/usr/bin/env python3
"""PreToolUse hook: allow only vetted read-only commands in an audit project.

Deny-lists of command names cannot hold: `echo hi > file` writes a file without
naming a single denied command, and `python3 -c` can do anything at all. So this
works the other way round — every Bash command is blocked unless it matches an
allow-list of read-only invocations, and the file-editing tools are blocked
outright.

Wire it up in .claude/settings.json:

  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash|Write|Edit|NotebookEdit|MultiEdit",
       "hooks": [{"type": "command",
                  "command": "python3 .claude/skills/drive-detox/hooks/readonly_guard.py"}]}
    ]
  }

Exit 0 allows the call. Exit 2 blocks it and shows the reason to Claude.
"""
import json
import re
import shlex
import sys

BLOCKED_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}

# Read-only skill scripts. analyze_inventory, detox, mcp_bridge and drive_inventory
# write only to an output path the caller names, which is why --save/--output are
# restricted to /tmp below.
SKILL_SCRIPTS = (
    "detox.py",
    "scan_local.py",
    "analyze_inventory.py",
    "drive_inventory.py",
    "mcp_bridge.py",
    "check_deny_rules.py",
)
# Commands that cannot modify anything, for looking around.
SAFE_COMMANDS = {
    "ls", "pwd", "cat", "head", "tail", "wc", "file", "stat", "du", "df",
    "echo", "date", "whoami", "which", "python3", "md5", "shasum", "basename",
    "dirname", "env", "printenv", "uname", "sw_vers", "claude",
}
# Shell metacharacters that could smuggle a write past the allow-list.
SHELL_TRICKS = re.compile(r"(>>|[>;&|`]|\$\(|<\()")
WRITE_FLAGS = ("--output", "--save", "--skip-report")


def deny(reason):
    print(f"Drive Detox read-only guard: {reason}", file=sys.stderr)
    sys.exit(2)


def check_output_paths(parts):
    """Script output must land in /tmp, never in the folder being audited."""
    for index, part in enumerate(parts):
        target = None
        if part in WRITE_FLAGS and index + 1 < len(parts):
            target = parts[index + 1]
        elif part.startswith(tuple(f"{flag}=" for flag in WRITE_FLAGS)):
            target = part.split("=", 1)[1]
        if target and not target.startswith("/tmp/"):
            deny(f"{part} must write inside /tmp, got {target!r}. "
                 "The audit never writes next to the files it reads.")


def check_bash(command):
    if not command or not command.strip():
        deny("empty command")
    if SHELL_TRICKS.search(command):
        deny("redirection, pipes and command substitution are blocked, because "
             "`echo text > file` writes a file without naming a write command. "
             "Run one plain command at a time.")
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        deny(f"could not parse the command ({exc})")
    if not parts:
        deny("empty command")

    program = parts[0].rsplit("/", 1)[-1]
    if program == "python3":
        script = next((part for part in parts[1:] if part.endswith(".py")), None)
        if script is None:
            deny("python3 is allowed only to run the skill's own scripts, "
                 "never -c, -m or a script from elsewhere.")
        if script.rsplit("/", 1)[-1] not in SKILL_SCRIPTS:
            deny(f"{script} is not one of the skill's read-only scripts: "
                 + ", ".join(SKILL_SCRIPTS))
        check_output_paths(parts)
        return
    if program == "find":
        if any(part in ("-delete", "-exec", "-execdir", "-ok", "-okdir") for part in parts):
            deny("find may list files, but not -delete or -exec.")
        return
    if program not in SAFE_COMMANDS:
        deny(f"{program!r} is not on the read-only allow-list. This project audits "
             "files and never changes them; nothing here needs it.")


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        deny("could not read the tool call, so it is refused by default.")

    tool = payload.get("tool_name") or payload.get("toolName") or ""
    if tool in BLOCKED_TOOLS:
        deny(f"{tool} is blocked. This project is read-only: it audits files and "
             "proposes a cleanup, and never creates or edits one.")
    if tool == "Bash":
        tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
        check_bash(tool_input.get("command", ""))
    sys.exit(0)


if __name__ == "__main__":
    main()
