# Dev contract: module interfaces

Every module is built against this file. If you need to change a signature,
stop and say so in your report. Don't change it silently.

Spec: `docs/superpowers/specs/2026-11-09-digital-twin-design.md` (read
Revision B: PII is a setting).
Run tests: `cd skills/digital-twin && .venv/bin/pytest -q`.
Python 3.12 venv already set up. Runtime deps are only `mcp`, `model2vec` and
`PyYAML`; dev also gets `pytest`. Use only the stdlib besides those.

**Never** put any real person's name, profession or domain in code, prompts,
templates or tests. Use placeholders such as "Project Atlas", "Northwind Ltd",
"a former manager", "Asha", "Ravi".

## Brain layout (TWIN_HOME, default ~/.twin/brain)

```
raw/brain.sqlite        sources, items, held, categories, rules, personas
privacy.yaml            PII modes (copied from templates/ on init)
schema.yaml             completeness template (copied on init)
dictionary.json         relation vocabulary + aliases
active                  active persona slug (one line)
questions.json  ledger.json  corrections.jsonl  log.jsonl
personas/<slug>/contract.md soul.md voice.md rules.md      (manager-written)
personas/<slug>/facts.jsonl graph.json dictionary.json pages/*.md
                index.md profile.md index.sqlite vectors.npy vec_ids.json (generated)
audit.html
```

## store.py

- `TEMPLATES: Path` points at `skills/digital-twin/templates`.
- `home() -> Path`: `Path(os.environ.get("TWIN_HOME", "~/.twin/brain")).expanduser()`
- `init(home: Path | None = None) -> Path`: creates the dirs, copies `privacy.yaml` and `schema.yaml` from TEMPLATES if missing, creates the SQLite schema (idempotent), and writes an empty `dictionary.json` `{"relations": {}, "aliases": {}}` if missing.
- `db() -> sqlite3.Connection`: opens `raw/brain.sqlite` with `row_factory = sqlite3.Row`, calling `init()` first if needed.
- `read_json(path, default)`, `write_json(path, obj)` (atomic: tmp then rename, indent=1, ensure_ascii=False, sort_keys=False)
- `append_jsonl(path, obj)`, `read_jsonl(path) -> list[dict]`
- `log(event: str, **kw)`: appends `{"ts": iso, "event": event, **kw}` to log.jsonl
- `persona_dir(slug) -> Path`, `questions_path()`, `ledger_path()`, `corrections_path()`, `dictionary_path()`, `active_path()`, `privacy_path()`, `schema_path()`

SQLite schema (exact):

```sql
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, origin TEXT, added TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, text TEXT NOT NULL, about TEXT NOT NULL DEFAULT 'me',
  category TEXT NOT NULL, edge_s TEXT, edge_rel TEXT, edge_o TEXT, src TEXT, since TEXT,
  conf TEXT DEFAULT 'medium', by TEXT DEFAULT 'doc', status TEXT DEFAULT 'active',
  created TEXT, updated TEXT);
CREATE INDEX IF NOT EXISTS items_cat ON items(category);
CREATE INDEX IF NOT EXISTS items_about ON items(about);
CREATE INDEX IF NOT EXISTS items_status ON items(status);
CREATE TABLE IF NOT EXISTS held(token TEXT PRIMARY KEY, type TEXT, value TEXT, src TEXT);
CREATE TABLE IF NOT EXISTS categories(slug TEXT PRIMARY KEY, description TEXT);
CREATE TABLE IF NOT EXISTS rules(persona TEXT, category TEXT, decision TEXT, PRIMARY KEY(persona, category));
CREATE TABLE IF NOT EXISTS personas(slug TEXT PRIMARY KEY, audience TEXT, include TEXT, exclude TEXT, created TEXT);
```

## ids.py

- `norm(text) -> str`: NFKC, lowercased, whitespace collapsed, trailing punctuation stripped
- `fact_id(text) -> str`: `"f-" + sha1(norm(text))[:10]`
- `source_id(text) -> str`: `"s-" + sha1(text)[:10]`
- `slug(name) -> str`: ascii-folded, lowercased, non-alphanumerics become `-`, collapsed, max 60 chars; `"me"` stays `"me"`

## gate.py: PII by setting

Types: `email`, `phone`, `address`, `password`, `bank_account`, `card`, `gov_id`.
Modes: `allow` | `hold` | `drop`. Defaults are in `templates/privacy.yaml`:
email, phone and address are hold; password, bank_account, card and gov_id are drop.

- `Finding = {"type": str, "start": int, "end": int}`. It never contains the value.
- `settings() -> dict[type, mode]` reads the brain's privacy.yaml, falling back to the template.
- `scan(text) -> list[Finding]` finds all types regardless of mode, non-overlapping, sorted.
- `redact(text, src=None) -> tuple[str, list[dict]]`. For each finding: allow leaves it as is; hold replaces it with `⟦<type>:<6hex>⟧` (hex = sha1(value)[:6]) and adds a held row `{"token","type","value","src"}`; drop replaces it with `⟦<type>⟧`. Idempotent: the text inside existing tokens is never re-scanned.
- `TOKEN_RE`: matches both token forms.
- `strip_tokens(text) -> str` removes all tokens and tidies leftover whitespace and punctuation (" , " becomes ",").
- `unhold(text, held: dict[str, str], modes: dict | None = None) -> str` replaces hold tokens whose type is now `allow` with their value, and strips every other token.
- `set_mode(type, mode) -> None` updates privacy.yaml (ValueError on unknown type or mode).

Detection notes (the tests pin these): email, including "name at gmail dot com"; phones written as
`+91 98765 43210`, `98-765-43210`, `(415) 555-0134` and `+44 20 7946 0958`, but not
years, counts or percentages ("in 2004", "team of 12", "40%", "14 awards", "1,200 people");
address = number + street word (Street/St/Road/Rd/Avenue/Ave/Lane/Ln/Marg/Nagar/Boulevard)
or a postcode right after a city word or a comma; password = value after
`password|passwd|pwd|passcode|pin` followed by `:`, `=` or `is`; bank_account = IBAN, or digits
after "account (no|number|#)", or IFSC/SWIFT/sort code with value; card = 13–19 digits
passing Luhn (spaces and dashes allowed); gov_id = PAN `[A-Z]{5}\d{4}[A-Z]`, Aadhaar
`\d{4} \d{4} \d{4}`, SSN `\d{3}-\d{2}-\d{4}`, passport after "passport".

## raw.py

- `add_source(text, origin) -> str` redacts, stores (upsert by `source_id` of the redacted text), stores held rows, and logs.
- `add_items(items: list[dict]) -> list[str]`. Each input is `{text, category, about="me", edge=None|{"s","rel","o"}, src=None, since=None, conf="medium", by="doc"}`. It redacts `text` and `edge.o`. `id = fact_id(redacted text)`. Upserts: an existing `by="you"` row is never overwritten by `by="doc"`. An unknown category raises `ValueError("unknown category: <slug>; known: [...]")`. Returns the ids.
- `items(status="active", categories: list[str] | None = None) -> list[dict]`. The dict uses the column names, with `edge` as a dict or None instead of the edge_* fields. Ordered by `created, id`.
- `get(item_id) -> dict | None`, `set_status(item_id, status) -> None`
- `held_map() -> dict[token, value]`
- `apply_privacy() -> dict` re-runs `redact` over all source and item text, for allow → hold/drop changes. Returns `{"sources": n_changed, "items": n_changed}`.
- `stats() -> dict` gives counts by status and by category.

## policy.py

- `class NoActivePersona(Exception)`
- `define_category(slug, description)`, `categories() -> dict[slug, description]`
- `create_persona(slug, audience, include, exclude) -> Path` inserts the row, writes `contract.md`, and copies `soul.md`, `voice.md` and `rules.md` from TEMPLATES if absent.
- `personas() -> list[dict]`, `persona(slug) -> dict | None`
- `set_rule(persona, category, decision)` (decision in allow|deny, otherwise ValueError), `rule(persona, category) -> str | None`, `rules(persona) -> dict[category, decision]`
- `set_active(slug)` (ValueError if unknown), `active() -> str` (raises NoActivePersona if the file is missing or the persona is unknown)
- `dictionary() -> dict`, `define_relation(name, inverse=None, symmetric=False, single=False, words=(), inverse_words=())`, `add_alias(alias, canonical)`

Dictionary shape: `{"relations": {rel: {"inverse": str|None, "symmetric": bool, "single": bool,
"words": [...], "inverse_words": [...]}}, "aliases": {alias: canonical}}`.
`words` are what the object end is called, seen from the subject (`spouse_of` gives "spouse", "wife",
"husband", "married"). `inverse_words` name the subject end, seen from the object (`works_at` gives
"employee", "works at", "staff"). `single` means one value per subject (spouse_of, born_in).

## graph.py (pure: no store access)

- `canonical(name, dictionary) -> str` folds aliases case-insensitively. "I", "me", "my" and "myself" become "me".
- `build_graph(items: list[dict], dictionary: dict) -> dict` gives `{"nodes": {name: {"aliases": [...], "facts": [ids]}}, "edges": [{"s","rel","o","fact"}]}` with names canonicalised. The `me` node is always present. Symmetric edges are stored once, and an inverse relation is stored one way round. Output is deterministic and sorted.
- `mentions(q, graph, dictionary) -> {"entities": [names in order], "relations": [(rel, direction) in order]}`, where direction is `"out"` for words and `"in"` for inverse_words.
- `walk(q, graph, dictionary) -> list[dict]`. Each result is `{"kind": "chain"|"set"|"count"|"path", "answer": str | list[str], "chain": [[s, rel, o], ...], "restated": str}`. Chains are possessives and "of" ("my spouse's school", "the school of my spouse"); "who else <rel> <X>" gives the set excluding the subject; "how many" gives a count; "how is A connected to B" gives the BFS shortest path (≤4 hops, both directions). `restated` echoes the question words: "The school of the spouse of me: X".

## router.py

- `needs_graph(q, graph, dictionary) -> bool` is true if q names a non-`me` node, uses any relation word, or matches `how many|who else|the same .* as|connected|related to`.

## search.py (pure over a facts list)

- `build_index(persona_dir: Path, facts: list[dict]) -> None` writes `index.sqlite` (FTS5 `facts(id UNINDEXED, about, text)`, porter unicode61 tokenizer). If model2vec loads (env `TWIN_EMBED_MODEL`, default `minishlab/potion-base-8M`), it also writes `vectors.npy` (float32, L2-normalised) and `vec_ids.json`.
- `open_ro(persona_dir) -> Index` opens SQLite with `file:...?mode=ro` (uri=True).
- `Index.search(q, k=8) -> list[{"id","about","text","score"}]` fuses BM25 and cosine with RRF (k=60). BM25 only if vectors are missing or model2vec is unavailable. The query is sanitised for FTS5 by OR-ing word tokens.
- `Index.close()`

## build.py · questions.py · corrections.py · tidy.py · audit_html.py (wave 2)

- `build.rebuild(persona) -> dict`, `build.rebuild_all() -> dict`
- `questions.sync() -> dict`, `questions.refresh_gaps() -> int`, `questions.next(n=2) -> list[dict]`,
  `questions.answer(qid, text="", decision=None, status=None) -> dict`, `questions.all(status=None) -> list[dict]`
- Question: `{id, kind: approval|info|conflict, persona, category, about, field, text, examples, waiting, score, status: open|answered|declined|snoozed, asked, created, until}`
- `corrections.record(said, should, target, persona=None, payload=None) -> dict`, where target is one of voice|rules|item|category|schema|soul|privacy
- `tidy.run() -> dict`, `audit_html.run() -> dict`

## MCP tool names (wave 3; agents' docs rely on these)

Server `twin-manage` (`python -m brainkit.mcp_manage`): `init`, `status`, `add_source(text, origin)`,
`add_items(items)`, `define_category(slug, description)`, `define_relation(name, inverse, symmetric, single, words, inverse_words)`,
`add_alias(alias, canonical)`, `create_persona(slug, audience, include, exclude)`, `set_rule(persona, category, decision)`,
`set_active(slug)`, `set_privacy(type, mode)`, `sync`, `next_questions(n)`, `answer(question_id, text, decision, status)`,
`record_correction(said, should, target, persona, payload)`, `tidy`, `audit`, `gate_scan(text)`, `list_items(category, status)`.

Server `twin-read` (`python -m brainkit.mcp_read`): `brief()` (soul, voice and rules of the active persona),
`search(q)`, `walk(q)`, `page(name)`, `profile()`. No other tools.
