# Published validation and consumer checks

Release 0.1.0 bundles the tools, tests, native agent folders, configuration example,
OAuth helpers, privacy/security documents and gateway contract. No `.venv`, local
practice state, Google configuration, OAuth client or credentials are published.

Maintainer validation on macOS, Python 3.14.2, Claude Code 2.1.296:

- 56 Doctor Appointment tests passed, including mock Google API boundaries.
- 116 existing Drive Detox tests passed after adding the new skill.
- Skill frontmatter validation passed.
- Consumer smoke check passed without Google or a model API.
- Actual native CLI inventory audit: six patient tools and thirteen doctor tools,
  connected narrow MCP, no built-in shell/file/web tools or forbidden probe calls.
- macOS Keychain backend available; process/credential ACL isolation unverified.
- Google OAuth and live API writes not performed; live operation remains disabled.

`references/validation.json` records SHA-256 hashes of distributed files and actual
runtime observations. `scripts/verify_package.py` checks those hashes in under a
second. The manifest checks consistency with the fetched release, not authenticity
against a compromised publisher; pin the raw URL and clone to a trusted Git commit
for repeatability. It excludes itself and generated runtime files.

Maintainers run regression tests when changing code. GitHub CI repeats them on
Python 3.11 and 3.14 without Claude login, Google credentials or API calls. Unit
launcher tests use a simulated CLI; only the separate native CLI audit establishes
actual tools. CI never claims it verified a user's runtime security.

Consumers do not need to rebuild the scheduling logic or rerun the full suite.
Run integrity verification and `tools/smoke.py`, then audit **their** Claude runtime
once when launching the agents. Google authorization, selected resource access,
Keychain behavior, interactive policy and gateway identity are machine-specific
and cannot be inherited from maintainer test results. Repeat an audit after CLI
updates or policy changes. If tests are desired or code is modified:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Fresh consumer evaluation is conducted after publication: remove publisher-created
build copies, start in a new folder, give an independent subagent only the public
skill URL and a normal setup request, and verify it downloads the entire bundle,
uses the shipped tools, demonstrates practice mode and reports exact launch
commands and security limits. The evaluator must not access live Google data or
modify the remote repository. Record its result in the maintainer handoff rather
than editing the tested release solely to announce that it was tested.
