# Testing

## Unit tests

```bash
cd skills/digital-twin
.venv/bin/pytest -q
```

Needs the dev requirements: `.venv/bin/pip install -r requirements-dev.txt`.

## Evals

The evals run the agents against a public test corpus and score them. See
[evals/README.md](evals/README.md). Corpora are downloaded outside the repo and
never committed.

The eval runner launches each agent the way a host app would: only that agent's
MCP server (`--strict-mcp-config`), and the twin limited to its read tools. That
lives in the eval harness, not the package. Results by round are in
[evals/REPORT.md](evals/REPORT.md).
