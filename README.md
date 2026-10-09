# CatalEx Everyday Skills

**Small AI workflows. Real everyday outcomes.**

An open-source collection of practical AI workflows for everyday life and work.

## Skills
| Skill | Outcome | Status |
|---|---|---|
| [Drive Detox](skills/drive-detox/README.md) | Audit a local folder or Google Drive read-only: biggest files, stale files, duplicate groups, and a cleanup plan you approve before anything moves. | Local mode works out of the box; Drive mode needs a `drive.readonly` token or your own MCP connection |

## Getting started
Not technical? Start with the Drive Detox [walkthrough](skills/drive-detox/WALKTHROUGH.md).

```bash
git clone https://github.com/catalex-ai/everyday-skills.git
cd everyday-skills
./install.sh
```

That installs Drive Detox into `~/drive-detox` with its read-only guard, checks the guard works, and tells you the two steps left.

Then just ask — "clean up my Downloads folder" — and the skill runs itself. By hand it is one command:
```bash
python3 skills/drive-detox/scripts/detox.py --target ~/Downloads
```

## Principles
- Outcome-first: solve real problems.
- Reusable: make workflows easy to inspect and adapt.
- Transparent: document requirements, limitations, and permissions.
- Safe by default: prefer least privilege.
- Testable: include examples and tests where practical.

## Add a skill
Use [templates/skill-template](templates/skill-template) as the starting point. Each skill should have `SKILL.md`, `README.md`, examples, tests where applicable, and clear safety boundaries.

## License
MIT. See [LICENSE](LICENSE).
