# Version 0.2.0 verification

This release uses native Codex and Claude instructions/skills/configuration. It
removes `launch.py` and adds doctor-side booking through the shared scheduler.
No credentials, native auth links, local sample database or runtime logs ship.

Publisher checks:

- 59 offline unit/security/API-boundary tests, and 116 existing Drive Detox tests.
- Native skill validation and offline consumer smoke.
- Codex 0.162.1 effective app-server configuration, role instructions/skills,
  six/fourteen-method MCP inventories and OS read/write/network denial probes.
- Claude Code 2.1.296 actual tool inventories: approved Skill plus six/fourteen
  role methods; no shell/file/web built-ins.
- Actual native Codex patient and doctor booking conversations, including separate
  request/confirmation turns and trusted synthetic write verification.

`references/validation.json` contains publisher results and file hashes.
`scripts/verify_package.py` checks consistency with that release, not authenticity
against a compromised publisher. Pin a trusted Git commit for repeatability.
The full suite runs in CI on Python 3.11 and 3.14 without model/Google calls.

Consumers use hash verification and `tools/smoke.py`, then run a local native
runtime audit. They do not rebuild tools or repeat the entire suite. Google consent,
Keychain behavior, trusted identity and effective permissions are machine-specific;
prior publisher tests cannot verify them on another machine. Re-audit after runtime
or policy changes. For changed code, run maintainer regressions with the shipped
locked API dependencies:

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
