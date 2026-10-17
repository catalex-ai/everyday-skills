# Doctor Assistant

Two ready-made appointment assistants for a clinic, for **Claude Code** or **Codex**:
a **Patient Assistant** (book, move or cancel your own appointment) and a
**Doctor Assistant** (see the day, book for a patient, block time, change hours).
Bookings are kept either in the clinic's **Google Calendar + Sheets** or on
**this computer**; you choose during setup.

Give your coding assistant this prompt:

> Read https://raw.githubusercontent.com/catalex-ai/everyday-skills/main/skills/doctor-appointment/SKILL.md
> and set up the Doctor Assistant here.

It installs the prebuilt tools, asks a few plain questions (clinic name, hours,
where to keep bookings, and for Google which calendar and spreadsheet) and tells
you how to open both assistants. You do not run any commands.

Real-patient sign-in is not available yet: the Patient Assistant works with two
test patients, Patient A and Patient B.

## Open an assistant

Codex: double-click **Patient Assistant.command** or **Doctor Assistant.command**.
From a terminal (either runtime):

```sh
./doctor-assistant/start.sh patient
./doctor-assistant/start.sh doctor
./doctor-assistant/start.sh patient claude
./doctor-assistant/start.sh doctor claude
```

The shortcuts only pass the restricted native CLI options below. They do not
install dependencies, sign in to Google or change policy.

## Where bookings are kept

| | Google Calendar + Sheets | This computer |
|---|---|---|
| Good | Phone/Calendar view, spreadsheet register, survives a lost laptop | No sign-in, works offline, private |
| Less good | One-time Google sign-in; each change shows an Approve pop-up | Only on this computer; no spreadsheet |

Only the setup helper (`tools/admin.py`, run by a setup assistant) can choose or
switch. The Patient and Doctor assistants have no tool for it and cannot change
the calendar or spreadsheet. Switching does not copy existing bookings.

```sh
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py status
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py clinic-settings --set clinic_name="Example Clinic" --set opening=09:00
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py use-laptop
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py list-calendars
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py google-setup --calendar "Clinic" --new-register "Clinic appointments" [--client PATH]
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py activate
```

`google-setup` reuses a working sign-in stored in macOS Keychain; `--client` is
needed only for the first sign-in. `--register-url LINK` uses an existing
spreadsheet instead of creating one. `activate` reads the chosen calendar and
spreadsheet once and switches both assistants to Google. Google mode is bound to
those two resources: if they change or the sign-in stops working, every request
fails with a clear message and nothing falls back to this computer. Package
updates do not turn Google mode off. `google-revoke` signs out and turns it off.

Each Google write (book, move, cancel, block, settings) needs a click on the
macOS "Doctor Assistant approval" pop-up, which the assistants cannot press.

### Patients hear about clinic changes

Each appointment remembers the time the patient last agreed to. When the clinic
moves, cancels or books an appointment for a patient (through the Doctor
Assistant, or by editing or deleting the event directly in Google Calendar), the
patient's next request to the Patient Assistant first returns only a plain
notice, e.g. "The clinic moved your appointment from Tue 13 Oct, 4:05 pm to
Wed 14 Oct, 10:00 am.", which the assistant tells them before anything else.
Each change is delivered once (`config/notices-seen.json`). There is no
email/SMS: patients learn about it the next time they use the assistant.
Bookings made before this version only report direct deletions until the
doctor first changes them through the assistant.

### Google sign-in file

Needed once per clinic Google account (a publisher-provided client is not shipped):

1. In [Google Cloud Console](https://console.cloud.google.com/), create or pick a
   project and enable **Google Calendar API** and **Google Sheets API**.
2. **Google Auth Platform**: set Branding (app name, support email), Audience
   (Internal if offered, otherwise External and add your account as a test
   user), and Data Access for the three scopes below.
3. **Clients** → create client → type **Desktop app** → download the JSON to a
   private folder outside `doctor-assistant/`. Never paste its contents in chat.

Scopes: `calendar.events`, `calendar.readonly`, `spreadsheets`. No Drive or Gmail.
Sign-in uses a browser loopback flow and stores the token only in macOS Keychain
(no plaintext fallback). Testing-mode tokens may expire; run `google-setup
--client PATH` again. If the machine is lost, also remove the app from your
Google Account's third-party connections.

The register has `Appointments` (ID, start/end, status, kind, last seen, issue)
and `Daily Summary` sheets. Calendar is the source of truth; a spreadsheet
failure never undoes a booking. Cancelling removes the event from the calendar
view; the spreadsheet keeps the history. Installs from before 0.4.0 left
cancelled events visible (marked Free), which look booked; remove them once with
`admin.py hide-cancelled`.

# For maintainers

Setup above does not run any of this. Consumers reuse the published results.

## Native permissions

`native-prepare` links an existing Codex login into the two isolated `.codex`
homes without reading it. Without a login, run `CODEX_HOME="$PWD/.codex" codex
login` in each role folder. Claude uses its existing login.

## Codex: two native terminals

Terminal 1, from your workspace root:

```sh
cd doctor-assistant/patient-agent
CODEX_HOME="$PWD/.codex" codex --no-daemon --strict-config --dangerously-bypass-hook-trust
```

Terminal 2:

```sh
cd doctor-assistant/doctor-agent
CODEX_HOME="$PWD/.codex" codex --no-daemon --strict-config --dangerously-bypass-hook-trust
```

Codex natively loads `AGENTS.md`, `.agents/skills/appointments` or `clinic`, and
`.codex/config.toml`. The scoped home prevents inherited user MCP/plugins/settings. Both role configs
default to `gpt-6-luna`; the native audit checks the actual thread model. If Luna
is unavailable on your account, stop rather than silently choose another model.
Claude defaults to **Haiku** through its role settings. The native audit records
the actual Haiku model; Claude does not run the OpenAI Luna model.
The native clinic permission profile grants only minimal runtime files and role
instructions/skills read access; it denies config/credential reads, all writes
and command networking. Shell, browser, apps, plugins, image/file viewing,
subagents and permission-request tools are disabled. MCP is restricted to the
role's approved clinic methods. A native PreToolUse guard rejects other local tools.
Codex may still advertise `apply_patch`; native permissions reject its writes.
Its sandboxed Code Mode may orchestrate approved tools; this does not grant shell,
filesystem or unrestricted network access.

The hook-trust flag runs only the integrity-checked shipped guard without a second
trust dialog. **It does not bypass approvals or sandboxing.** Alternatively review
and trust it in `/hooks`, then omit this flag. Do not use the unrelated
`--dangerously-bypass-approvals-and-sandbox`. This is tested on Codex 0.162.1;
unsupported versions must fail the audit rather than weaken the profile.

Synthetic Patient B, instead of A, adds this native config override:

```sh
CODEX_HOME="$PWD/.codex" codex --no-daemon --strict-config --dangerously-bypass-hook-trust -c 'mcp_servers.clinic.args=["../tools/server.py","--role","patient","--patient","patient-b"]'
```

This explicit local test identity is not authentication for live patients.

## Claude Code: the same two folders

In either role folder, run this native command:

```sh
claude --restricted --tools Skill --strict-mcp-config --mcp-config .mcp.json --setting-sources "" --plugin-dir .claude --append-system-prompt-file AGENTS.md --settings .claude/settings.json --permission-mode dontAsk --no-chrome
```

Claude receives `AGENTS.md` through its native prompt-file flag and loads the role skill through the explicitly selected local `.claude` plugin. `CLAUDE.md` also imports AGENTS.md for ordinary native discovery. Restricted-mode auto-discovery did not load project instructions/skills on the tested build; explicit native flags are required.
Only the role's skill and clinic MCP operations are authorized. Shell/file/web
built-ins are removed, hooks allow only that role's tools, and the fail-closed
Bash sandbox cannot retry outside its boundary. Native skills are used directly.
Tested on Claude Code 2.1.296. Plain `claude` or `codex` in a folder does not prove
permissions isolation; use the exact native command for the chosen runtime.

## Practice data and evaluations

```sh
python3 doctor-assistant/tools/admin.py practice-demo
python3 doctor-assistant/tools/audit.py --runtime codex
python3 doctor-assistant/tools/audit.py --runtime claude
```

The fixture uses the next working day in Asia/Kolkata. Patient A has `a-demo` and
`cancelled-demo`; B has `b-demo`; the doctor sees both active appointments and a
blocked range. First mock Sheets synchronization deliberately fails; retry succeeds.
`doctor_verify_synthetic_appointment` runs an isolated booking/cancellation/isolation
check without changing shared practice state. `doctor_book_appointment` books for
configured Patient A/B through the same scheduler, with action-bound confirmation.

Patient phrases: “Show my appointments”, “Book tomorrow at 14:00”, “Cancel my
appointment”, “What is the clinic address?” Doctor phrases: “Show tomorrow's
schedule”, “Book Patient B tomorrow at 16:00”, “Set duration to 20 minutes”,
“Block tomorrow 11:00–12:00”, “Sync the register”. Explicitly confirm displayed
proposals. Never enter real patient data in practice.

Configuration is conversational through doctor_configure_clinic: name, timezone,
working days (Monday=0), hours, breaks, duration, buffers, address/contact, resource
IDs and policies. Trusted code validates and persists it. Practice JSON is separate
from Google configuration; it is only the mock adapter's local sample database.
The live design uses Calendar as appointment truth, not that file or Sheets.

With no storage chosen, the sessions use this synthetic practice fixture. It is
for tests and evaluations only; setup always chooses Google or this computer.

Optional live end-to-end check (books and cancels one synthetic event, each
approved in the pop-up; not part of setup):

```sh
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py synthetic-google-test
```

An opt-in maintainer test actually starts native Codex sessions in both folders,
books one synthetic appointment through each role, views the doctor's schedule,
and verifies Patient B's isolated list:

```sh
python3 doctor-assistant/tests/run_native_sessions.py
```

This uses your Codex model connection and changes only synthetic practice state.
Reusable multi-day natural conversation evaluations use the same specification
for Codex Luna and Claude Haiku. Run them only in new output directories:

```sh
python3 doctor-assistant/tests/run_conversation_eval.py --runtime codex --output-dir /tmp/clinic-luna-eval
python3 doctor-assistant/tests/run_conversation_eval.py --runtime claude --output-dir /tmp/clinic-haiku-eval
```

These evaluations use native model connections and synthetic records, without
Google access. They save redacted transcripts and objective fixture checks. See
[the evaluation specification](tests/EVAL_SPEC.md). Published actual transcripts are available for
[Codex Luna](references/transcripts/luna.md) and
[Claude Haiku](references/transcripts/haiku.md), with
[validation results](references/conversation-validation.json). A separate
[fresh public-clone check](references/transcripts/fresh-clone.md) verifies native
booking and doctor visibility on both models. Passing a finite scenario does
not establish perfect conversation quality or authorize real-patient use.
Full offline regressions are included for maintainers and CI. See TESTING.md.



## Verified restrictions and remaining limits

See SECURITY.md and references/validation.json for publisher observations. Local
audits write config/audit-report.json. Codex audit queries the actual app-server
for effective config, active permissions, instruction/skill discovery and live
MCP inventory, then verifies denial of synthetic outside-folder reads, writes and
network access. Claude audit captures actual native model tool inventories.
A restriction is not passed merely because a setting exists in a file.

These checks do not certify the entire Codex built-in schema, all future interactive
policy changes, same-UID process isolation, Keychain ACLs, independently proven human
consent or trusted live clinic identity. Native shell/file tools are restricted;
MCP and hooks run in the trusted helper boundary outside the command sandbox.
A person with administrative OS access or native permission controls can change
configuration. A terminal exposed to untrusted humans needs managed policy and
OS account boundaries before real-patient use. No configuration file can replace
those boundaries. Real mode stays gated in trusted code.

Google mode has been exercised end to end with synthetic identities (booking,
register sync, duplicate retry, isolation, cancellation) on the publisher's
machine. Calendar has no atomic reservation guarantee, external writers can race
rechecks, and overlapping live reschedules are conservatively rejected. The
trusted helper runs as the same OS user as the sessions. This is not
certification for real patient data. Nothing sensitive is published.
