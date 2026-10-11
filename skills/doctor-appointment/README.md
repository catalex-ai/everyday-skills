# Doctor Assistant: two native agent terminals

**Prebuilt package for Codex and Claude Code. Synthetic scheduling works; live
patient mode remains disabled.** No Python launcher, application or installer.
The patient and doctor folders contain native instructions, skills, permissions
and separate narrow MCP surfaces backed by one shared Python scheduler.

Give your creation assistant this prompt:

> Read https://raw.githubusercontent.com/catalex-ai/everyday-skills/main/skills/doctor-appointment/SKILL.md
> and create the two native Doctor Assistant sessions here using the prebuilt tools.
> Demonstrate patient/doctor booking and ask whether I want Google authorization now.

The assistant downloads the **whole folder**, verifies published hashes, runs a
quick offline compatibility check, prepares native login/config and audits your
chosen runtime. It does not regenerate tools or repeat publisher tests. The original
creation session may have developer permissions; the patient session does not.

## Prepare once

After copying the bundle to `doctor-assistant/`, from your workspace root:

```sh
python3 doctor-assistant/scripts/verify_package.py
python3 doctor-assistant/tools/smoke.py
python3 doctor-assistant/tools/admin.py native-prepare
```

`native-prepare` is a trusted configuration/auth operation, not a session launcher.
It links your existing protected native Codex auth file into the two isolated
`.codex` homes without reading/copying its contents. If no existing login exists,
run `CODEX_HOME="$PWD/.codex" codex login` in each role folder. Native Claude uses
its existing login. No Google credentials are needed for practice.

## Open an assistant

After the one-time preparation, double-click **Patient Assistant.command** or
**Doctor Assistant.command** in Finder. These open native Codex on **GPT-6-Luna** with the tested
restrictions. The shortcuts use your login shell's PATH to locate the CLI.

From a terminal, the same minimal entry point supports either runtime:

```sh
./doctor-assistant/start.sh patient
./doctor-assistant/start.sh doctor
./doctor-assistant/start.sh patient claude
./doctor-assistant/start.sh doctor claude
```

The shortcuts only select the folder and pass the existing restricted native CLI
options. They do not install dependencies, authenticate Google, or change policy.
If macOS blocks a downloaded shortcut, review it and use Finder's Open action;
terminal invocation remains available. Missing CLIs fail without a fallback.

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

## Practice and verification

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

An opt-in maintainer test actually starts native Codex sessions in both folders,
books one synthetic appointment through each role, views the doctor's schedule,
and verifies Patient B's isolated list:

```sh
python3 doctor-assistant/tests/run_native_sessions.py
```

This uses your Codex model connection and changes only synthetic practice state.
Full offline regressions are included for maintainers and CI. Consumers need only
integrity, smoke and their local runtime audit. See TESTING.md.

## Connect Google during creation

The creation skill asks whether to connect Google now or stay in offline practice.
Only the human's choice starts authorization. Prepare optional Google dependencies
from your workspace root (the creation assistant can do this):

```sh
python3 -m venv doctor-assistant/.venv
doctor-assistant/.venv/bin/python -m pip install -r doctor-assistant/requirements.lock.txt
```


OAuth setup and access checks can run without enabling live appointments. These
commands are **not MCP tools**; the human must run them outside the patient/doctor sessions.
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

Google authorization has not been performed. Google connection during creation
requires a Desktop OAuth client and browser consent; live Calendar/Sheets writes
remain unverified. Calendar has no atomic reservation guarantee, external writers
can race rechecks, and overlapping live reschedules are conservatively rejected.
The staged real-resource synthetic verification is still gated by unresolved
security prerequisites. This is a working native practice package, not certification
for real patient data. Nothing sensitive is published.
