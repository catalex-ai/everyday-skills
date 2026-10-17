# CatalEx Everyday Skills

**Small AI workflows. Real everyday outcomes.**

An open-source collection of practical AI workflows for everyday life and work.
Each skill is something you hand to Claude Code or Codex: it sets itself up, asks
you a few plain questions, and then does one job well, with clear limits on what
it is allowed to touch.

| Skill | What you get | Status |
|---|---|---|
| [Doctor Appointment](skills/doctor-appointment/README.md) | Two chat assistants for a clinic: a **Patient Assistant** that books, moves and cancels a patient's own appointments, and a **Doctor Assistant** that runs the day's schedule, blocks time and sets hours, either as set appointment times or as a number of patients per day. Bookings live in Google Calendar + Sheets or on your computer. | Works with two test patients (Patient A and B). Real-patient use is blocked until identity and OS-level isolation are verified. |
| [Drive Detox](skills/drive-detox/README.md) | A read-only audit of a folder or Google Drive: biggest files, stale files, duplicate groups, and a cleanup plan you approve before anything moves. | Local folders work out of the box. Drive needs a `drive.readonly` token or your own MCP connection. |

## Doctor Appointment

Give Claude Code or Codex this prompt in the folder where you want the assistants:

> Read https://raw.githubusercontent.com/catalex-ai/everyday-skills/main/skills/doctor-appointment/SKILL.md
> and set up the Doctor Assistant here.

It downloads the tested tools, asks for your clinic's name, hours, how you take
bookings and where to keep them, and tells you how to open both assistants. You
don't run any commands. The [guide](skills/doctor-appointment/README.md) covers
what each assistant does, Google setup, permissions and the test suites.

## Drive Detox

Not technical? Start with the [walkthrough](skills/drive-detox/WALKTHROUGH.md).
Otherwise:

```bash
git clone https://github.com/catalex-ai/everyday-skills.git
cd everyday-skills
./install.sh
```

This installs Drive Detox into `~/drive-detox` with its read-only guard, checks
the guard works, and tells you the two steps left. Then just ask, for example
"clean up my Downloads folder", and the skill runs itself. By hand it's one
command:

```bash
python3 skills/drive-detox/scripts/detox.py --target ~/Downloads
```

## Principles

- **Outcome-first:** solve real problems.
- **Reusable:** workflows are easy to inspect and adapt.
- **Transparent:** requirements, limitations and permissions are documented.
- **Safe by default:** least privilege; nothing changes without your say-so.
- **Testable:** examples and tests wherever practical.

## Add a skill

Start from [templates/skill-template](templates/skill-template). Each skill needs
a `SKILL.md`, a `README.md`, examples, tests where they apply, and clear safety
boundaries. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
