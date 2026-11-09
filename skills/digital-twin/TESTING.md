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
