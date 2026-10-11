# Security model and audit

## Trust boundaries

The model is untrusted. `CLAUDE.md` and skills describe behavior and are not
security boundaries. The trusted Python service fixes role, subject and clinic
at session startup; tool arguments cannot supply them. Each operation centrally
authorizes role and clinic, validates argument keys/types, and enforces appointment
ownership before returning data. All responses omit raw Calendar descriptions,
patient contact, credentials and diagnostic text. Unexpected exceptions return
only class names. Google credentials never enter MCP or model output.

Patient listing uses one composite SHA-256 `patientScope` private property at
Google's server, then verifies owner/clinic in trusted code. Multiple Calendar
private-property filters would be OR; using clinic and owner separately could
retrieve other patients and is prohibited. Busy queries use freebusy, not full
calendar retrieval. Rescheduling does not remove an owned interval from merged
freebusy ranges, because this could hide overlapping appointments. The patient
cannot invoke full schedule, configuration or Sheets tools, even by calling MCP
names not advertised in its tool inventory. No general-purpose operation is exposed.

Doctor management verifies a session-bound authenticated doctor for its clinic.
Synthetic doctor identity only authorizes the synthetic fixtures. Patient A/B are
explicit launcher selections, not authentication for live patients. No live
identity is inferred from Google OAuth. Future gateway integration must satisfy
[GATEWAY.md](GATEWAY.md); a role/subject argument in conversation is never sufficient.

## Runtime controls

`tools/launch.py` starts installed native Claude with `--restricted`, no built-in
tools, only an explicit MCP configuration, no user/project/local settings, disabled
hooks/skills, disabled Chrome, `dontAsk`, and fail-closed Bash sandbox settings.
It rejects versions lacking required flags. Only minimal non-secret environment
variables pass through. Synthetic MCP has no Google imports or credential-reading
operation. Skill workflows are explicitly included in the system instructions.
Native `.mcp.json` and project settings support discovery but are not a substitute
for this launcher. Do not resume unrestricted developer sessions in agent folders.

The developer session used to build this package had unrestricted filesystem and
shell access. Those tools are not exposed in the resulting clinic sessions.
Humans controlling the OS/launcher can change code or launch an unrestricted CLI;
protecting against that administrator is outside this design. Same-user process
compromise is not isolated, and remains a production blocker.

## Audit method and results

On 2026-10-11, `tools/audit.py` launched both actual Claude Code 2.1.296 print-mode
sessions with the same launcher flags, captured the real `system/init` tool lists
and MCP connection status, and prompted safe synthetic attempts to use Bash,
Read, WebFetch and permission changes. Both returned successfully and invoked
only their permitted clinic information/status operation. Patient inventory had
six approved tools; doctor inventory had thirteen. No unexpected tools or forbidden
calls were observed. Missing init data, timeout, unexpected/missing tools or an
unsuccessful CLI exit fails or leaves the result unverified. An absent inventory
never passes on the basis of configuration text.

This verifies exposed model tool capabilities for those probes. It does not prove
OS isolation, immunity to future CLI vulnerabilities, every inherited managed
customization, interactive mode changes, or independent user-consent provenance.
Re-audit after Claude updates or policy changes. Running audit uses Claude's
ordinary model service; unit tests and practice-demo do not.

| Control | Evidence | Result |
|---|---|---|
| Patient tool separation | Actual CLI init + MCP direct-denial tests | Passed |
| Doctor tool separation | Actual CLI init + MCP authorization tests | Passed |
| No model shell/file/web tools | Actual init inventories and probes | Passed for tested sessions |
| Ownership and identity-argument rejection | Trusted-code tests | Passed in practice |
| Response credential/contact redaction | Canary tests + error sanitization | Passed in tested paths |
| OS credential storage backend | Actual macOS Keychain backend selection | Available |
| Credential ACL/process isolation | No separate OS account/broker supplied | Unverified |
| Trusted live patient/doctor identity | No gateway available | Unverified |
| Human-consent provenance | Tokens visible to model | Unverified |
| Interactive session effective policy | Print-mode equivalents probed | Unverified beyond tested flags |
| Live Google API authorization/write/reconciliation | No client/resources supplied | Unverified |

`admin.live_gate()` denies live-patient and synthetic real-resource mutations
without an escape flag. This intentionally keeps the system in synthetic mode.
Do not remove the gate merely because the mock suite passes.

## Scheduling and reporting reliability

Local file locks serialize synthetic operations across the two terminals. Live
Calendar is not a reservation transaction system. Deterministic base32hex-compatible
SHA-256 IDs and same-ID retries recover ambiguous insert outcomes; explicit
readback is required for success. Availability is rechecked before writing; a
post-write overlap is reported. There is no distributed or atomic booking guarantee.
Changes use ETag preconditions and require reconfirmation after direct doctor edits.
Confirmation tokens expire, are single-use, and bind exact actions/event versions.
Tokens are workflow controls, not proof of human consent.

Sheets stores a reporting projection keyed by stable appointment ID. It uses
repeatable deterministic overwrites instead of appends and rejects malformed
headers/duplicate IDs. Failed sync never alters Calendar. Missing events preserve
previous rows and mark review. A timeout during Sheets write can be reconciled again.
Only one trusted register writer should run; external spreadsheet editors/writers
can race. Google adapters and staged verification are mocked locally, not certified
by live integration tests. Recurring event management is outside the initial narrow
managed-appointment scope; unmanaged events still block availability.

## Sources inspected

Official [CLI reference](https://code.claude.com/docs/en/cli-reference),
[settings](https://code.claude.com/docs/en/settings),
[MCP](https://code.claude.com/docs/en/mcp),
[skills](https://code.claude.com/docs/en/skills), and
[sandbox scope](https://code.claude.com/docs/en/sandboxing), plus installed `claude --help`.
The Bash sandbox explicitly excludes MCP, hooks, and built-in file/web tools.
Google [Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[extended-property filter semantics](https://developers.google.com/workspace/calendar/api/guides/extended-properties),
[event insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert),
[event list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list), and
[Sheets values API](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/update).
