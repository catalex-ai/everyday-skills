# Golden evals (Claude Haiku)

Runs real `claude --restricted --model haiku` Patient and Doctor sessions against an
isolated synthetic copy of this package per case (never the live Google config),
grades each turn with deterministic state/tool/reply checks plus a Haiku judge.

```sh
python3 evals/golden_eval.py                                   # all suites, current prompts
python3 evals/golden_eval.py --cases B09,X05 --label retry-1     # subset (IDs or prefixes: P, SD, ...)
python3 evals/golden_eval.py --agent-snapshot evals/baseline-agent-snapshot --label baseline   # other prompts (below)
```

- Scenarios: `tests/scenarios/golden_dataset.json` (42), `sunrise_suite.json` (64, from the E2E spec) and `count_mode.json` (12).
- Live status: `evals/dashboard.html` (all runs; auto-refresh while running) and `evals/RESULTS.md`.
- Per run: `evals/runs/<label>/dashboard.html`, `RESULTS.md`, `cases/<ID>/result.json`, frozen `agent-snapshot/`.
- Transcripts: `tests/conversations/<ID>.md` (latest run of each case).

Dashboards, run folders and transcripts are generated and git-ignored.

To compare against older prompts, put them in a folder as `patient-AGENTS.md`,
`patient-SKILL.md`, `doctor-AGENTS.md`, `doctor-SKILL.md` and pass it with
`--agent-snapshot`. The prompts before the eval fixes are in commit `f8d2828`:

```sh
mkdir -p evals/baseline-agent-snapshot && cd evals/baseline-agent-snapshot
for r in patient:patient-agent:appointments doctor:doctor-agent:clinic; do IFS=: read role dir skill <<< "$r"
  git show f8d2828:skills/doctor-appointment/$dir/AGENTS.md > $role-AGENTS.md
  git show f8d2828:skills/doctor-appointment/$dir/.claude/skills/$skill/SKILL.md > $role-SKILL.md; done
```

States: PASS (all checks + judge), WARN (checks pass, judge flags quality), FAIL (a check
failed), ERROR (harness/session error), BLOCKED (not runnable on this architecture; never
counted as pass).

Every turn asserts: role-allowed tools only, Haiku model, synthetic-only results, no token
or internal-ID leak, no success claim without a confirmed write, proposals change nothing,
and (patients) no own-identity confusion.
