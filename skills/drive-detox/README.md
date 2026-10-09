# Drive Detox

**Find out what is actually eating your storage — then get a cleanup plan you approve before anything moves.**

Read-only by design. It audits, labels, and recommends. It never deletes, moves, or renames a file.

First skill in CatalEx Everyday Skills.

## Two modes

**Local mode** works right now, with no accounts and no setup. Point it at a folder.

**Drive mode** audits your real Google Drive, two ways: a `drive.readonly` access token you mint yourself, or a read-only Google Drive MCP server connected through claude.ai. This repo bundles no credentials and no Drive connection — see [references/google-drive-setup.md](references/google-drive-setup.md).

Three routes, easiest first:

1. **Google Drive for desktop.** Install it, sign in, and your Drive is a folder — `detox.py --target auto` finds it. No Cloud console, no tokens. Claude can install it for you with your approval.
2. **The Drive API**, for checksum-accurate duplicates across a whole Drive without downloading it. Needs a `drive.readonly` token you mint yourself; `drive_inventory.py` issues HTTP GET requests and nothing else, and refuses to list a single file if the token carries any scope beyond read-only.
3. **A claude.ai MCP connector**, if you want Claude querying Drive live in conversation. The code path is built and tested — `mcp_bridge.py` normalizes whatever the server returns into the shared report, and `check_deny_rules.py` verifies the write tools are blocked before you connect — so only the authentication is left to do.

## Install into a project

```bash
./install.sh            # installs into ~/drive-detox
./install.sh ~/folder   # or somewhere you choose
```

The installer copies the skill, installs the read-only settings and guard hook, proves the guard blocks a delete and a file write, and prints the two steps left. Then open Claude Code in that folder and ask for an audit, or invoke `/drive-detox`.

Lost? `python3 scripts/detox.py --setup` prints an ordered guide based on what is actually on your machine.

## How read-only is enforced

Not by the prompt. By [`hooks/readonly_guard.py`](hooks/readonly_guard.py), a PreToolUse hook the installer wires in:

- `Write`, `Edit`, `NotebookEdit` and `MultiEdit` are blocked outright
- every Bash command is blocked unless it matches an allow-list of read-only invocations
- redirection, pipes, command chaining and command substitution are rejected, because `echo text > file` writes a file without naming a single write command — which is exactly how a deny-list of command names gets bypassed
- `python3` may run only this skill's own scripts, never `-c` or `-m`
- `--output`, `--save` and `--skip-report` must point inside `/tmp`, so an audit never writes next to the files it reads

Tested live: asked to create a file by any means and then delete one, Claude was blocked at shell redirection, blocked again at the `Write` tool ("Write is disabled for this session, in subagents as well as here"), and blocked at `rm`. Nothing changed on disk. 28 tests cover the guard.

Not technical? [WALKTHROUGH.md](WALKTHROUGH.md) is the short version: install once, then ask in plain English. You run three things, and only three, because nobody can do them for you — sign in to Google, approve an install, and decide what gets deleted.

## Try it in one minute

Installed as a skill, you just talk to it — "clean up my Downloads folder", "my Drive is full, what's eating the space" — and Claude runs everything itself.

By hand, it is one command:

```bash
python3 skills/drive-detox/scripts/detox.py --target ~/Downloads
```

It scans, analyzes, and prints a finished report. `--target auto` finds Google Drive for desktop, `--diagnose` shows what is set up, `--save <path>` keeps a copy.

## What the report tells you

- File count and a breakdown by type
- Total known size, plus how many files report no size
- The 10 biggest files, with links or paths
- Everything untouched past your age cutoff (default 730 days)
- Duplicate groups by MD5 checksum, plus weaker same-name candidates
- A KEEP / REVIEW / ARCHIVE CANDIDATE / DUPLICATE CANDIDATE label per finding

## Run the tests

```bash
python3 -m unittest discover -s skills/drive-detox/tests -v
```

116 tests. Full walkthrough, including how to prove the read-only claim yourself: [TESTING.md](TESTING.md).

## Known limits

- Google account storage also counts Gmail and Photos, so Drive totals will not match your storage bar.
- Google Docs/Sheets/Slides usually report no size. Unknown is not zero.
- Last-modified is a review signal, not proof a file is unused.
- Same name is not proof of identical content. Same checksum is strong evidence.
- Archiving does not free storage. Only emptying trash does, and that stays a manual step.
- Local mode skips hidden files, symlinks, and `.git` / `node_modules` / `.venv` by default, and skips checksums above 512 MB.

## Safety

A skill prompt is not a security boundary. Enforce read-only at the OAuth scope and permission layers too — both are covered in [references/google-drive-setup.md](references/google-drive-setup.md). Never paste credentials into chat or commit them.
