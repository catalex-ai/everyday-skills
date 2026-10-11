# Doctor Assistant: two local Claude Code terminals

**Prebuilt synthetic practice package; real-patient mode is disabled.**
Tested on macOS with Claude Code 2.1.296 and Python 3.14; CI repeats offline regression tests. Claude or Codex can fetch this skill and prepare the same shipped tools.
The patient/doctor runtime uses native Claude Code. No Codex restricted runtime,
application, separate installer or hosted service is included.

Give your coding assistant this prompt:

> Read https://raw.githubusercontent.com/catalex-ai/everyday-skills/main/skills/doctor-appointment/SKILL.md
> and use the prebuilt package to set up Doctor Assistant in this workspace.
> Demonstrate offline patient isolation, then give me the two restricted terminal
> launch commands. Do not regenerate the tools or enable real-patient mode.

The assistant clones the public repository and copies this **whole folder** to
`doctor-assistant/`. Downloading SKILL.md alone omits the implementation. Record
or pin the fetched Git commit for repeatable results; the final maintainer handoff
also supplies an immutable raw URL. Existing installations are never overwritten.
See [SKILL.md](SKILL.md) for assistant instructions and [TESTING.md](TESTING.md)
for published test evidence and checks needed on a new machine.

Patient tools check slots, book, show only owned appointments, cancel/reschedule,
and answer configured administrative questions. Doctor tools view schedules,
configure the clinic, block/unblock time, review conflicts and reconcile reporting.
Both use `tools/core.py`. Google Calendar is the intended authoritative live source;
Sheets is only reporting. Offline practice uses shared, synthetic mock state.

## Launch the two terminals

After the assistant copies the package to `doctor-assistant/`, prepare dependencies
once from your workspace root (the assistant can execute these development commands):

```sh
python3 doctor-assistant/scripts/verify_package.py
python3 doctor-assistant/tools/smoke.py
python3 -m venv doctor-assistant/.venv
doctor-assistant/.venv/bin/python -m pip install -r doctor-assistant/requirements.lock.txt
```

Offline practice can use Python 3.11+ without `.venv` or Google dependencies.
For the following two terminals, start from your workspace root:

Terminal 1:

```sh
cd doctor-assistant/patient-agent
../.venv/bin/python ../tools/launch.py --role patient
```

Terminal 2:

```sh
cd doctor-assistant/doctor-agent
../.venv/bin/python ../tools/launch.py --role doctor
```

Patient B, in place of Patient A:

```sh
../.venv/bin/python ../tools/launch.py --role patient --patient patient-b
```

**Do not substitute plain `claude`.** Native folder instructions, skills and MCP
configuration exist, but folder configuration alone is not security isolation.
The launcher starts native Claude Code with `--restricted --tools ""`,
`--strict-mcp-config`, explicit role-specific MCP, empty setting sources,
`dontAsk`, no Chrome, disabled hooks/skill execution, and a fail-closed Bash
sandbox. It provides the agent instructions explicitly, scrubs inherited secret
environment variables and accepts no extra Claude flags. Your existing Claude
subscription login is used; practice requires no Google credentials. Interactive
Claude sessions require Claude's normal model connection. The offline practice
commands below need neither network nor an external model API.

Native skills are retained as workflow references; execution is disabled in the
restricted sessions to avoid loading other local customizations. The launcher
provides equivalent workflows in the explicit system prompt.

## Offline practice and tests

From your workspace root:

```sh
python3 doctor-assistant/tools/admin.py practice-reset
python3 doctor-assistant/tools/admin.py practice-demo
doctor-assistant/.venv/bin/python -m unittest discover -s doctor-assistant/tests -v
python3 doctor-assistant/tools/admin.py audit
```

Reset only synthetic state; do not reset while sessions are carrying pending
confirmations. Fixture date is the next working day in Asia/Kolkata. Patient A
sees `a-demo` and `cancelled-demo`; B sees only `b-demo`. The doctor sees the two
active appointments and `blocked-demo`. The first register sync fails deliberately;
the second succeeds. A repeated sync must have three historical appointment rows.

Patient phrases: “Show my appointments”, “Show available slots on [fixture date]”,
“Book the first available slot”, “Cancel my appointment”, “What is the address?”
Doctor phrases: “Show [fixture date]'s schedule”, “Set appointment duration to 20
minutes”, “Block [fixture date] 11:00–12:00”, “Sync the register”, “Review issues”, “Run synthetic appointment verification”.
Respond to displayed confirmation proposals explicitly. Do not use real patient
names, contacts, appointment IDs or diagnoses in practice.

Configuration is conversational through `doctor_configure_clinic`: name, timezone,
working days (Monday=0), hours, breaks, duration, buffer, address, contact, resource
IDs and policies. Trusted code validates and persists it. Practice configuration
is separate from `config/google-clinic.json`. No manual YAML/source edits needed.

## Connect Google from a human-owned terminal

OAuth setup and access checks can run without enabling live appointments. These
commands are **not MCP tools**; the human must run them outside the Claude prompt.
Do not paste credential contents or tokens into chat.

1. In [Google Cloud Console](https://console.cloud.google.com/), create/select a
   project. Enable **Google Calendar API** and **Google Sheets API**.
2. Under **Google Auth Platform**, configure Branding (app name/support email),
   Audience (Internal if available, otherwise External), and Data Access for the
   three scopes listed below. For an External app in Testing, add your Google
   account as a test user. Google may expire testing refresh tokens; reconnect
   when required. Workspace administrator approval may be needed.
3. Under **Clients**, create an OAuth client with application type **Desktop app**.
   Download its JSON outside this repository, e.g. into a private directory under
   your home directory. Protect the file; never send its contents to the assistant.
4. Use a separate test clinic calendar and spreadsheet initially. In Calendar's
   settings, copy the explicit **Calendar ID** under Integrate calendar; do not use
   `primary`. Copy the real spreadsheet ID from its `/spreadsheets/d/ID/edit` URL.
   Your Google account must have write access to both. Existing non-matching
   `Appointments` worksheet headers cause a refusal to overwrite.
5. Run these from your workspace root:

```sh
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py google-configure
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py google-connect --client "$HOME/private/desktop-client.json"
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py google-status
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py open-spreadsheet
```

The JSON path above is an example; use your actual downloaded client path. The
configuration command prompts for non-secret fields. Keep `clinic_id` synthetic
until trusted live identity integration is implemented. OAuth opens a browser or
prints the authorization URL. The local helper handles a random-port loopback
callback, OAuth state validation and offline consent via `InstalledAppFlow`.
It stores credentials only in **macOS Keychain** after read-verifying both resources.
No deprecated out-of-band or invented device flow is used. Missing Keychain
backend stops the operation, with no plaintext fallback. No token is printed.
A 180-second consent timeout can be retried. API write access remains unverified
until a consented write actually succeeds.

Scopes: `calendar.events` for event management, `calendar.readonly` for explicit
calendar metadata and busy checks, and `spreadsheets` for register read/write.
No Drive, Gmail or general Calendar MCP access. Google grants scopes across the
account's accessible resources; trusted adapters restrict calls to configured IDs.

Revoke Google authorization and delete stored credentials:

```sh
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py google-revoke
```

Revocation must succeed before local deletion, so a failed network request can be
retried. If the machine is lost, revoke the app from your Google Account's
third-party connections. No secrets are kept in configuration, logs or Git.

## Real Google synthetic verification: blocked pending security prerequisites

```sh
doctor-assistant/.venv/bin/python doctor-assistant/tools/admin.py synthetic-google-test
```

This operation deliberately refuses writes while trusted gateway identity,
independent human-confirmation provenance and the OS credential boundary are
unverified. No flag or conversational override enables it. `tools/verification.py`
contains the staged workflow for use after those prerequisites are implemented
and audited: verify selected resources; obtain human CREATE consent; create and
read back one stable synthetic Calendar event; reconcile/open actual Sheets;
wait for human row verification; reconcile again and reject duplicate IDs;
obtain separate CANCEL consent; verify cancellation in Calendar and Sheets;
check isolated synthetic identities; rerun actual CLI permission audit. It prints
a recovery event ID before the write and reports pending cleanup on interruptions.
**This workflow has been tested with mocks, not with live Google.**

The `Appointments` worksheet contains ID, start/end, status, kind, last-seen and
issue. `Daily Summary` aggregates day/status counts. Issues fit in the appointment
row, so no extra Sync Issues worksheet is created. Unexpected deletion retains
history and marks review required. Logical cancellation retains the Calendar
record, marks private clinic status `cancelled`, and makes it transparent; it
does not delete audit history. Reconciliation never rolls back Calendar bookings.

## Enforced controls and remaining limits

Maintainer CLI probes showed exactly **6 patient tools** and **13 doctor tools**, no
built-in machine/file/network tools, connected role-specific MCP, and no forbidden
probe calls. See [SECURITY.md](SECURITY.md) and `references/validation.json` for
published evidence and limits; your local audit writes `config/audit-report.json`. These are actual observed inventories, not just configuration checks.
The mock suite checks authorization, isolation, injections, leakage, conflicts,
retry/recovery, timezones and reconciliation. No live API success is claimed.

The narrow MCP helper runs as the same macOS user; the Bash sandbox does not
isolate MCP or the Claude process. Keychain backend availability was verified;
ACL isolation was not. No trusted CatalEx gateway was available. Confirmation
tokens do not prove human approval. Tool inventories were verified for print-mode
sessions, not every future interactive/plugin/managed-settings combination. Claude
itself still communicates with Anthropic. Calendar lacks atomic reservations;
external writers can race a recheck. Google freebusy cannot safely subtract one
appointment, so live reschedules overlapping the original slot are conservatively
rejected. Direct removal of ownership metadata requires doctor review.

Accordingly real-patient use and the live test remain blocked. This is a tested
practice implementation with Google adapters and OAuth tooling, **not the full
production definition of done**. Published code contains no tokens, local state or patient records.
