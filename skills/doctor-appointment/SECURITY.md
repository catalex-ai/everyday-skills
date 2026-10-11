# Security model: native Codex and Claude sessions

## Boundaries

The model, chat claims, event text and skill instructions are untrusted. Native
instructions/skills route workflow; they are not security boundaries. Shared
`tools/core.py` authorizes every call using an immutable session identity and
clinic, validates arguments, checks ownership, strips raw event/contact text,
and refuses patient management/Sheets operations even when called directly.
Patient listing uses a single composite patient-and-clinic filter at Google's
server; repeated private property filters are OR, so separate clinic/owner filters
would be unsafe. Availability uses busy intervals without event details.

Patient A/B and the doctor are synthetic test identities selected outside chat by
native MCP configuration. They cannot authorize real patient data. Doctor-side
booking only accepts configured synthetic Patient A/B; a model-supplied arbitrary
patient identity is rejected. Future live identity needs the broker in GATEWAY.md.
Google OAuth grants application resource access, not patient/doctor identity.

## Native runtime configuration

No Python session launcher exists. Codex natively loads AGENTS.md, .agents/skills
and the role's `.codex/config.toml` using a scoped CODEX_HOME. This avoids inherited
user MCP/settings/plugins and starts an independent native CLI instance with
`--no-daemon`. The named `clinic` permission profile grants minimal platform reads
and native instruction/skill reads, denies `.codex` (including linked provider
auth), grants no writes, and disables command networking. Effective features
disable shell, apps, plugins, browser/computer use, file/image viewing, agents and
permission requests. The required narrow clinic MCP advertises an explicit tool
allowlist. The native hook rejects other local calls, including apply_patch.
Only this server's authorized operations use approval mode `approve`; this does
not grant the model machine permissions. Scheduling confirmations remain separate.

Codex can still advertise apply_patch, but native permissions reject writes before
approval, including direct calls. Its sandboxed Code Mode orchestrates exposed
tools and is not an arbitrary Python/shell/filesystem interface. The audit does
not enumerate the complete built-in schema; this remains explicitly unverified.

Claude explicitly loads AGENTS.md with its native prompt-file flag and its role skill with the local plugin flag. Restricted project auto-discovery omitted both on the tested build; the audit now checks the actual namespaced skill inventory.
The documented `--restricted --tools Skill --strict-mcp-config` command removes
shell/file/web built-ins and restricts MCP to `.mcp.json`. Only the role's Skill
invocation is allowed by permissions and the trusted hook. Settings are supplied
explicitly with empty inherited setting sources. The Bash sandbox fails closed
and cannot retry unsandboxed. Folder configuration alone is insufficient.

Hooks are defense in depth: Codex documents that some errors/unsupported paths can
fail open. The code returns explicit denial on malformed input, but native
filesystem/network permissions and disabled features remain independent controls.
The hook-trust bypass flag only trusts the integrity-checked guard, not permissions.
Humans may instead review/trust the hook in `/hooks`; never disable it to proceed.
MCP and hooks run outside the command sandbox as trusted helper processes. They
must not expose arbitrary code, file, credential or network operations.

## Actual verification

`tools/audit.py` is an opt-in test tool, not a runtime launcher. It inspects actual
native sessions, not just configuration files:

- Codex app-server `config/read` returns effective features/settings.
- `thread/start` returns the active permission profile and actual instruction sources.
- `skills/list` confirms role-specific native discovery.
- `mcpServerStatus/list` queries connected, actual tool inventories and detects
  unexpected servers/methods. Six patient methods and fourteen doctor methods.
- `codex sandbox -P clinic` runs synthetic OS probes: an outside-folder read,
  a file creation and network request are denied. A successful unsandboxed control
  request distinguishes network denial from an unrelated network failure.
- Claude print-mode initialization provides actual model tool inventories: Skill
  plus the six/fourteen clinic methods, with no unexpected tools.
- `tests/run_native_sessions.py` starts real native Codex threads in both folders,
  carries booking through separate request/confirmation turns, verifies the trusted
  Calendar-mock write, views the schedule and tests isolated patient records.

The local/CI unit suite also tests role authorization, guessed IDs, direct/indirect
injection, contact/credential canaries, guard denial, booking races, retry recovery,
timezones, Google API boundaries and register failures. Native model tests are
opt-in and never part of offline CI. Full Codex built-in schema completeness and
all future human-interactive mode changes are not marked verified.

## Limits and live gate

Native terminal owners can change CLI settings or permissions; administrative OS
users can edit code. A session exposed to untrusted humans requires enforced managed
policy and separate OS identity/credential boundaries before real-patient operation.
A scoped config or hook does not make those controls immutable.

Same-UID helper/Keychain ACL isolation, trusted live identities, independently
proven human consent and live Google API tests remain unverified. A linked native
Codex provider login is not Google OAuth and is never copied/read into model context.
Google refresh tokens stay in macOS Keychain, with no plaintext fallback.
`admin.live_gate()` keeps real-patient scheduling and real-resource test writes
disabled; no conversation or config flag bypasses it. Connection/read checks can
be performed through a human-consented setup operation without enabling booking.

Calendar has no atomic reservation guarantee. Shared scheduling rechecks before
writes, uses stable deterministic IDs and readback after ambiguous timeouts,
reports external overlaps, and uses ETags for changes. Confirmation tokens bind
single-use, expiring exact actions, but are not proof that a human approved.
Sheets deterministically reconciles by stable ID; failure never undoes Calendar.
Disappearing events retain historical rows marked for review. Only one trusted
register writer is supported; spreadsheet edits may race it. Logical cancellation
retains Calendar history and makes the event transparent. Live reschedules that
overlap merged freebusy intervals are conservatively rejected. Recurring management
is outside the initial narrow scope.

## Sources inspected

Official OpenAI [configuration reference](https://developers.openai.com/codex/config-reference/),
[permission profiles](https://developers.openai.com/codex/permissions/),
[app-server protocol](https://developers.openai.com/codex/app-server/),
[native hooks](https://learn.chatgpt.com/docs/hooks), and installed CLI/schema.
Official Claude [CLI](https://code.claude.com/docs/en/cli-reference),
[skills](https://code.claude.com/docs/en/skills),
[MCP](https://code.claude.com/docs/en/mcp),
[settings](https://code.claude.com/docs/en/settings) and
[sandbox scope](https://code.claude.com/docs/en/sandboxing).
Google [Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[extended-property filtering](https://developers.google.com/workspace/calendar/api/guides/extended-properties),
[Calendar events](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert),
and [Sheets values](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/update).
