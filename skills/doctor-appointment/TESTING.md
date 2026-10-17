# Version 0.2.4 verification

This release uses native Codex and Claude instructions/skills/configuration. It
removes `launch.py` and adds doctor-side booking through the shared scheduler.
No credentials, native auth links, local sample database or runtime logs ship.

Publisher checks:

- 61 offline unit/security/API-boundary tests, and 116 existing Drive Detox tests.
- Native skill validation and offline consumer smoke.
- Codex 0.162.1 effective app-server configuration, role instructions/skills,
  six/fourteen-method MCP inventories and OS read/write/network denial probes.
- Claude Code 2.1.296 actual tool inventories: approved Skill plus six/fourteen
  role methods; no shell/file/web built-ins.
- Actual native Codex patient and doctor booking conversations, including separate
  request/confirmation turns and trusted synthetic write verification.

One patient per session: the launcher picks it with `--patient ID` (in
`.mcp.json` or `tools/server.py`); any `[A-Za-z0-9_-]{1,128}` ID works and its
record is created on first use. Patient A and B are the demo defaults used by the
shortcuts, demos, evals and smoke checks. `tests/test_patients.py` covers patient
IDs, isolation, names and doctor bookings for any known patient.

`references/validation.json` contains publisher results and file hashes.
`scripts/verify_package.py` checks consistency with that release, not authenticity
against a compromised publisher. Pin a trusted Git commit for repeatability.
The full suite runs in CI on Python 3.11 and 3.14 without model/Google calls.

Doctor setup runs none of these checks. It installs the published tools, saves
clinic details, then either keeps bookings on the computer (`use-laptop`) or signs
in to Google and runs `activate`, whose only check is reading the chosen calendar
and spreadsheet. Runtime audits (`tools/audit.py`) and the live synthetic
book/cancel check (`admin.py synthetic-google-test`) are maintainer tools. For
changed code, run maintainer regressions with the shipped locked dependencies:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

The optional `tests/run_native_sessions.py` uses real Codex sessions and model
connectivity but only synthetic fixtures; it preserves conversation state across
booking and confirmation. It changes shared practice appointments and writes a
local `config/native-e2e-report.json`. Do not run it against Google resources.
The runtime audit also uses model calls for Claude and controlled synthetic probes.
Native auth must be prepared first. No live Google success is claimed.

A fresh-folder subagent evaluates the pinned public skill after publication,
verifies the downloaded bundle, discovers native role skills/config, and exercises
actual synthetic Codex sessions. No source/receipt edits or full-suite rerun are
needed. The maintainer handoff records the fresh evaluation result.

Fresh consumer testing caught missing Claude restricted-mode skill discovery. Version 0.2.4 explicitly loads the local role plugin and AGENTS prompt file; the audit requires the actual namespaced role skill. No custom session wrapper is used.

Version 0.2.4 adds authorized doctor-only patient references and plain-language
role instructions. Natural multi-user conversational validation is run separately
from the focused tool-workflow smoke; progress alone is not a scenario pass.

The configuration tool publishes field types and the symmetric buffer semantics
so ordinary “five minutes before and after” maps to buffer_minutes=5. Unknown
separate before/after fields are rejected by trusted configuration validation.
