# Drive Detox

**Find out what is actually eating your storage — then get a cleanup plan you approve before anything moves.**

Read-only by design. It audits, labels, and recommends. It never deletes, moves, or renames a file.

First skill in CatalEx Everyday Skills.

## Two modes

**Local mode** works right now, with no accounts and no setup. Point it at a folder.

**Drive mode** audits Google Drive through a read-only Google Drive MCP server that you connect separately. This repo bundles no credentials and no Drive connection — see [references/google-drive-setup.md](references/google-drive-setup.md).

## Install into a project

```bash
mkdir -p .claude/skills
cp -R skills/drive-detox .claude/skills/drive-detox
```

Open Claude Code in that project and ask for an audit, or invoke `/drive-detox`.

Recommended: also copy [examples/claude-settings-readonly.json](examples/claude-settings-readonly.json) to `.claude/settings.json` so the write tools are denied at the permission layer, not just by the prompt.

## Try it in one minute

```bash
python3 skills/drive-detox/scripts/scan_local.py ~/Downloads --output /tmp/inventory.json
python3 skills/drive-detox/scripts/analyze_inventory.py /tmp/inventory.json --older-than-days 730
```

Write the inventory outside the repo — it lists your real file names.

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

14 tests. Full walkthrough, including how to prove the read-only claim yourself: [TESTING.md](TESTING.md).

## Known limits

- Google account storage also counts Gmail and Photos, so Drive totals will not match your storage bar.
- Google Docs/Sheets/Slides usually report no size. Unknown is not zero.
- Last-modified is a review signal, not proof a file is unused.
- Same name is not proof of identical content. Same checksum is strong evidence.
- Archiving does not free storage. Only emptying trash does, and that stays a manual step.
- Local mode skips hidden files, symlinks, and `.git` / `node_modules` / `.venv` by default, and skips checksums above 512 MB.

## Safety

A skill prompt is not a security boundary. Enforce read-only at the OAuth scope and permission layers too — both are covered in [references/google-drive-setup.md](references/google-drive-setup.md). Never paste credentials into chat or commit them.
