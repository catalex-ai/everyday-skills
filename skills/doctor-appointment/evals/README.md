# Golden evals (Claude Haiku)

Runs real `claude --restricted --model haiku` Patient and Doctor sessions against an
isolated synthetic copy of this package per case (never the live Google config),
grades each turn with deterministic state/tool/reply checks plus a Haiku judge.

```sh
python3 evals/golden_eval.py                                   # both suites, current prompts
python3 evals/golden_eval.py --cases B09,X05 --label retry-1     # subset (IDs or prefixes: P, SD, ...)
python3 evals/golden_eval.py --agent-snapshot evals/baseline-agent-snapshot --label baseline   # original prompts
```

- Scenarios: `tests/scenarios/golden_dataset.json` (42) and `tests/scenarios/sunrise_suite.json` (64, from the spec).
- Live status: `evals/dashboard.html` (all runs; auto-refresh while running) and `evals/RESULTS.md`.
- Per run: `evals/runs/<label>/dashboard.html`, `RESULTS.md`, `cases/<ID>/result.json`, frozen `agent-snapshot/`.
- Transcripts: `tests/conversations/<ID>.md` (latest run of each case).

States: PASS (all checks + judge), WARN (checks pass, judge flags quality), FAIL (a check
failed), ERROR (harness/session error), BLOCKED (not runnable on this architecture; never
counted as pass).

Every turn asserts: role-allowed tools only, Haiku model, synthetic-only results, no token
or internal-ID leak, no success claim without a confirmed write, proposals change nothing,
and (patients) no own-identity confusion.
