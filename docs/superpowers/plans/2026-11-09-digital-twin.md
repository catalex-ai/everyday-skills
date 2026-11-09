# Digital Twin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `skills/digital-twin`: a twin manager agent (write) and a twin agent (read only) over one local brain folder, plus an eval harness that hill-climbs both on a downloaded public-figure corpus.

**Architecture:** The `brainkit` Python package holds all logic. Two stdio MCP servers expose it: `mcp_manage` (write tools; every write goes through `gate.check`) and `mcp_read` (read only, active persona only). Persona folders are rebuilt from approved raw items by code, with no model involved. Agents are Claude Code folders with CLAUDE.md and a skill.

**Tech Stack:** Python ≥3.11, stdlib sqlite3 (FTS5), `mcp`, `model2vec`, `PyYAML`, pytest.

**Spec:** `docs/superpowers/specs/2026-11-09-digital-twin-design.md`

## Global Constraints

- Dependencies: only `mcp`, `model2vec`, `PyYAML` at runtime, plus `pytest` for dev.
- Brain path is `TWIN_HOME` env var, otherwise `~/.twin/brain`. Never inside the repo.
- No person's name, profession or domain appears in skill code, prompts, templates or committed eval files. The eval seed is CLI-only, and corpora live in `~/.twin-corpora/`.
- No PII on disk in any zone: email, phone, street address, postcode, ID numbers, personal URLs or handles, full date of birth, pay amounts.
- Approval is per persona × category, never per item.
- The twin's read server opens only `personas/<active>/`, and SQLite with `mode=ro`.
- Gate findings report type and offset, never the matched value.

## Review Focus

1. A link or long document with 20 facts where 15 fall in already-approved categories: those 15 land in the persona at once, and exactly one question is created per new category. Test in Task 2.
2. A PII value that is split or disguised ("name at gmail dot com", "+91 98xxx 12345", "98-765-43210"): the gate still finds it. Test in Task 1.
3. An answer to an approval question arrives after more items in that category were added: all waiting items flow, including the later ones. Test in Task 2.
4. `active` is missing or points at a deleted persona: read tools return a clear error, never a fallback to another persona. Test in Task 5.
5. The same entity under two names ("Red Co" / "Red Co Pvt"): aliases from the dictionary merge them in graph and pages. Test in Task 3.

---

### Task 1: Package skeleton, store paths, ids, PII gate

**Files:**
- Create: `skills/digital-twin/brainkit/__init__.py`, `store.py`, `ids.py`, `gate.py`
- Create: `skills/digital-twin/templates/privacy.yaml`, `skills/digital-twin/requirements.txt`, `skills/digital-twin/pyproject.toml` (pytest config only)
- Test: `skills/digital-twin/tests/test_gate.py`, `tests/test_store.py`

**Interfaces:**
- Produces: `store.home() -> Path`; `store.init(home=None) -> Path` (creates the zones and copies templates); `store.read_json(p, default)`, `store.write_json(p, obj)` (atomic); `store.append_jsonl(p, obj)`, `store.read_jsonl(p) -> list`; `store.log(event: str, **kw)`
- Produces: `ids.fact_id(text: str) -> str` (`f-` + 10 hex chars of sha1 of normalised text); `ids.source_id(text) -> str` (`s-`…); `ids.slug(name: str) -> str`
- Produces: `gate.check(text: str) -> list[Finding]` where `Finding = {"type": str, "start": int, "end": int}`; `gate.require_clean(text: str) -> None`, which raises `PIIError(findings)`

- [ ] Step 1: Tests. `check("mail me at a.b@x.io")` gives type `email`. Also: `"+91 98765 43210"`, `"98-765-43210"` and `"(415) 555-0134"` give `phone`; `"name at gmail dot com"` gives `email`; `"https://linkedin.com/in/foo"` and `"@foo_bar"` give `url`/`handle`; `"born 2 November 1965"` gives `dob`; `"salary of ₹40,00,000"` gives `pay`; `"PAN ABCDE1234F"` gives `id`. Negatives: `"In 2004 I led a team of 12"`, `"won 14 awards"` and `"Q3 revenue grew 40%"` give `[]`. No Finding ever contains the matched string.
- [ ] Step 2: Run `cd skills/digital-twin && .venv/bin/pytest -q`. Expect FAIL.
- [ ] Step 3: Implement. Patterns load from `privacy.yaml` (`patterns: {type: regex}`, plus `context_words` for `dob` and `pay`). For `store.init`, copy `templates/*` into the brain only if missing.
- [ ] Step 4: Run the tests. Expect PASS.
- [ ] Step 5: Commit `feat(twin): store, ids, PII gate`.

### Task 2: Raw items, categories, rules, sync with approval questions

**Files:**
- Create: `brainkit/policy.py`, `brainkit/raw.py`, `brainkit/questions.py` (approval part)
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: Task 1
- Produces: `raw.add_source(text, origin) -> sid` (gated); `raw.add_items(items: list[dict]) -> list[id]` (gated on `text` and on edge values; upsert by id; sets `id`, `by` defaulting to `doc`, `status` `active`); `raw.items(status="active") -> list`
- Produces: `policy.define_category(slug, description)`; `policy.categories() -> dict`; `policy.set_rule(persona, category, decision: "allow"|"deny")`; `policy.rule(persona, category) -> str|None`; `policy.create_persona(slug, audience, include, exclude)` (writes contract.md, copies soul/voice/rules templates); `policy.personas() -> list`; `policy.set_active(slug)`; `policy.active() -> str` (raises `NoActivePersona`)
- Produces: `questions.sync() -> dict` (returns `{persona: {"allowed": n, "waiting": n, "denied": n}}`; creates or updates one open approval question per persona × unreviewed category with `waiting` count and 2 example texts; closes approval questions whose rule now exists; calls `build.rebuild` for every persona whose allowed set changed)
- Produces: `questions.answer(qid, text, decision=None)`. For approval: decision allow|deny → `set_rule`, then `sync`.

- [ ] Step 1: Tests. Two personas `pro` and `home`; `pro` allows `work`. Add 20 items: 15 `work`, 3 `family`, 2 `health`. After `sync`: `pro` has 15 allowed and 5 waiting. Exactly 2 approval questions exist for `pro` (family, health) and 3 for `home`, and none per item. Add 2 more `family` items, then answer the `pro`/family question deny: there are 0 waiting family items for pro, and the question is closed. Answer `home`/family allow: all 5 family items are in `home`'s facts.jsonl. Create a persona `third` later: questions are only for the 3 categories with no rule. `add_items` with an email in its text raises `PIIError` and writes nothing.
- [ ] Step 2: Run. Expect FAIL.
- [ ] Step 3: Implement. Leave `build.rebuild` as a stub that writes `facts.jsonl` only; Task 3 fills it in.
- [ ] Step 4: Run. Expect PASS.
- [ ] Step 5: Commit `feat(twin): raw items, category rules, approval sync`.

### Task 3: Persona build: facts, graph, pages, profile, search index

**Files:**
- Create: `brainkit/build.py`, `brainkit/graph.py` (build part), `brainkit/search.py`
- Test: `tests/test_build.py`, `tests/test_search.py`

**Interfaces:**
- Consumes: Task 2 (`raw.items`, `policy.rule`, `store.read_json(policy/dictionary.json)`)
- Produces: `build.rebuild(persona) -> dict` (counts). It writes `facts.jsonl`, `graph.json` (`{"nodes": {name: {"aliases": [...], "type": str}}, "edges": [{"s","rel","o","fact"}]}`), `pages/<slug>.md` (Now line = first fact about the entity, then all facts with `^id`), `index.md`, `profile.md` (facts about `me` grouped by category), and `index.sqlite`. It writes only allowed items.
- Produces: `graph.canonical(name, dictionary) -> str` (alias folding, case-insensitive); `dictionary.json` shape: `{"relations": {rel: {"inverse": str|None, "symmetric": bool, "words": [str]}}, "aliases": {alias: canonical}}`
- Produces: `search.open_ro(persona_dir) -> Index`; `Index.search(q, k=8) -> list[{"id","text","score"}]`. FTS5 BM25 plus model2vec cosine fused by RRF (k=60). BM25 only if model2vec is not importable. Vectors are stored as an `.npy` file next to the sqlite.

- [ ] Step 1: Tests. A denied item is absent from every file in the persona folder (grep its text). An edge `me —works_at→ Red Co Pvt` with alias `Red Co` gives one node. `rebuild` twice gives identical files. `search("where did I study")` ranks the education fact first, whether or not model2vec is installed (BM25 fallback tested by monkeypatching the import). `open_ro` cannot write (an INSERT raises).
- [ ] Step 2: Run. Expect FAIL.
- [ ] Step 3: Implement.
- [ ] Step 4: Run. Expect PASS.
- [ ] Step 5: Commit `feat(twin): deterministic persona build and hybrid search`.

### Task 4: Graph walk and router

**Files:**
- Modify: `brainkit/graph.py`
- Create: `brainkit/router.py`
- Test: `tests/test_walk.py`

**Interfaces:**
- Produces: `graph.walk(q, graph, dictionary) -> list[{"answer": str, "chain": [[s,rel,o]...], "restated": str}]`. It finds named entities in q (names and aliases, longest first; "my"/"I" maps to `me`) and relation words in order from the dictionary. It follows them hop by hop, in both directions, using inverses. Handles "how many X" (count) and "how is A connected to B" (BFS shortest path, max 4). `restated` = "The <rel word> of the <rel word> of <start>: <answer>".
- Produces: `router.needs_graph(q, graph, dictionary) -> bool`. True if q names a non-`me` node, uses a relation word, or matches `how many|who else|the same .* as|connected`.

- [ ] Step 1: Tests on a small fixture graph (me —spouse→ A; A —educated_at→ X; me —founded→ C; B —works_at→ C; D —works_at→ C): "where did my spouse study" gives X; "who else works at the company I founded" gives B and D; "how many people work at C" gives 2; "how is A connected to C" gives a path through me; "what did I study" makes `needs_graph` return False.
- [ ] Step 2: Run. Expect FAIL.
- [ ] Step 3: Implement.
- [ ] Step 4: Run. Expect PASS.
- [ ] Step 5: Commit `feat(twin): graph walk and router`.

### Task 5: Info-gap questions, corrections, MCP servers, CLI

**Files:**
- Modify: `brainkit/questions.py`
- Create: `brainkit/corrections.py`, `brainkit/mcp_manage.py`, `brainkit/mcp_read.py`, `brainkit/cli.py`, `templates/schema.yaml`
- Test: `tests/test_questions.py`, `tests/test_mcp.py`

**Interfaces:**
- Produces: `questions.refresh_gaps()`, which builds info and conflict questions using the weights in the spec. Required fields come from `schema.yaml` (`types: {type: {fields: [..], required: [..], weight: float}}`), checked against the categories and edges of items about each entity. A conflict is two active items with the same `edge.s` and `edge.rel` on a single-valued relation and a different `o`. `questions.next(n=2) -> list` (approval and conflict first, then info by score; increments `asked`; score × 0.5^asked). `answer(qid, text)` with status `declined` or `later` (7-day snooze) is supported.
- Produces: `corrections.record(said, should, target: "voice"|"rules"|"item"|"category"|"schema"|"soul", persona, payload)`. It appends to corrections.jsonl and applies the change: it appends to the persona's voice.md or rules.md, upserts the item with `by: you`, sets a rule, or edits the schema.
- Produces: MCP manage tools: `init`, `add_source`, `add_items`, `define_category`, `define_relation`, `add_alias`, `create_persona`, `set_rule`, `set_active`, `sync`, `next_questions`, `answer`, `record_correction`, `tidy`, `audit`, `status`, `gate_check`. MCP read tools: `brief`, `search`, `walk`, `page`, `profile`. `cli.py` mirrors the manage tools as subcommands (`python -m brainkit.cli status`).
- Produces: `mcp_read`, which resolves `policy.active()` on each call. A missing or unknown persona returns the error text "No active persona is set. Ask the owner to set one in the twin manager." and never falls back to another persona.

- [ ] Step 1: Tests. An item about project P with no `outcome` category creates an info question about P. Two conflicting `educated_at` items create one conflict question. `next(2)` returns approval before info. `declined` is never returned again. A correction targeting `voice` appends to `personas/pro/voice.md`. The read tools called in-process (functions, not over stdio) with `active` missing return the error text. `search` returns no item from a non-active persona.
- [ ] Step 2: Run. Expect FAIL.
- [ ] Step 3: Implement with `mcp.server.fastmcp.FastMCP`.
- [ ] Step 4: Run. Expect PASS. Also run `echo '{}' | timeout 3 .venv/bin/python -m brainkit.mcp_read`, which should start without a traceback.
- [ ] Step 5: Commit `feat(twin): questions, corrections, MCP servers, CLI`.

### Task 6: Audit page and tidy

**Files:**
- Create: `brainkit/audit_html.py`, `brainkit/tidy.py`
- Test: `tests/test_audit.py`

**Interfaces:**
- Produces: `audit.run() -> dict` (`{"pii_findings": [{"file","line","type"}], "personas": {...counts}, "waiting": n, "open_questions": n}`), which writes `brain/audit.html`: static, no network, showing per-persona counts, completeness by schema type, open questions, recent log, gate results, and items waiting per category.
- Produces: `tidy.run() -> dict`, which merges duplicate items (same normalised text), marks items `superseded` when a `by: you` item has the same subject and single-valued relation, folds 3+ voice examples sharing a tag into a rule line, then calls `sync`.

- [ ] Step 1: Tests. Plant an email in a page file by hand: `audit.run()` reports file, line and type `email`, with no value in the HTML. The HTML has no `http` URL except in origin lines. A duplicate item is merged.
- [ ] Step 2 to 4: Run, implement, pass.
- [ ] Step 5: Commit `feat(twin): audit page and tidy`.

### Task 7: Agents, templates, setup docs

**Files:**
- Create: `manager-agent/CLAUDE.md`, `manager-agent/.claude/skills/twin-manage/SKILL.md`, `manager-agent/.mcp.json`
- Create: `twin-agent/CLAUDE.md`, `twin-agent/.claude/skills/twin-reply/SKILL.md`, `twin-agent/.mcp.json`
- Create: `templates/soul.md`, `voice.md`, `rules.md`, `contract.md`; `SKILL.md` (setup); `README.md`, `PRIVACY.md`, `TESTING.md`; `start-manager.sh`, `start-twin.sh`
- Modify: repo `README.md` (skills table row)

**Content decisions:**
- Manager skill steps for each input: read, redact (other people's contact details out, names kept), write whole first-person sentences, choose or define a category (a generic noun phrase describing the type of information), add edges and relations, `sync`, then report in one line what landed, what is waiting and why. Ask only `next_questions` items, phrased as type-level questions for approvals. When creating a persona, pre-set rules from its contract where they are unambiguous.
- Twin skill: call `brief` once per conversation, then `search` (and `walk` when the question is relational), answer only from what the tools return, cite fact ids when asked, and say "I can't share that" or "I don't know" otherwise. Never reveal that personas exist.
- `start-twin.sh` runs `claude` in `twin-agent/` with `--strict-mcp-config --mcp-config .mcp.json --allowedTools "mcp__twin-read__*"`.
- No names or domains anywhere. Example text uses placeholders ("a former manager", "Project Atlas").

- [ ] Step 1: Write the files.
- [ ] Step 2: Verify with `grep -riE "shah|rukh|bollywood|actor|film" skills/digital-twin --exclude-dir=.venv`, which must return nothing.
- [ ] Step 3: Smoke test: `TWIN_HOME=$(mktemp -d) claude -p "status" ` from `manager-agent/` lists the brain status via MCP.
- [ ] Step 4: Commit `feat(twin): manager and twin agents, templates, docs`.

### Task 8: Eval harness

**Files:**
- Create: `evals/fetch_corpus.py`, `evals/fetch_pii.py`, `evals/make_qa.py`, `evals/simulate_owner.py`, `evals/run_round.py`, `evals/score.py`, `evals/personas.json`, `evals/README.md`
- Test: `tests/test_score.py`

**Interfaces:**
- `fetch_corpus.py --seed Q… --out ~/.twin-corpora/<name> [--max 60]`: walks Wikidata from the seed over the personal set (spouse P26, child P40, father P22, mother P25, sibling P3373, residence P551) and the professional set (educated at P69, employer P108, award received P166, owner of P1830, founded by P112 inverse, member of P463, owned by P127 inverse, notable work P800, position held P39). It downloads Wikipedia intros, splits the seed article by section into `sources/NN-<section>.txt`, holds back about 25% of the seed's sections into `heldout/`, and writes `truth.json` with `[s, prop_label, o, persona_class]`.
- `fetch_pii.py --n 40`: takes rows from the HF datasets-server API for `ai4privacy/pii-masking-200k` (English) and writes `pii.jsonl` (`text`, `spans:[{value,type}]`).
- `make_qa.py`: generates from truth, with no model, lookup, relation, multihop, aggregate and path questions in first person relative to the seed, each tagged with the persona that should know it and a must-not persona.
- `personas.json`: the eval-side plain description of what each test persona may know (`professional`, `personal`), used by the simulated owner. Generic wording.
- `simulate_owner.py`: one `claude -p --model haiku` call per question. Approval questions are answered allow or deny from personas.json. Info questions are answered only from `heldout/`, or "don't know".
- `run_round.py --corpus DIR --round N`: fresh `TWIN_HOME`; feeds sources in batches to the manager (`claude -p` in `manager-agent/`, `--model` flag, default sonnet) with PII probe rows interleaved; loops: manager `next_questions` → simulated owner → manager processes the answer (up to `--questions 25`); for each persona sets active and asks every QA item through the twin (`claude -p` in `twin-agent/`, default haiku); saves transcripts and `results.json`.
- `score.py results.json`: correct (any `must` alias in the reply, case-insensitive), evidence found (must-string in a tool result), leak-free per persona, PII spans on disk (grep each span value across TWIN_HOME, which must be 0), approval questions per persona × category (must be ≤1), info-question yield, a stage tag per miss. Prints a markdown table, which gets appended to `REPORT.md`.

- [ ] Step 1: `test_score.py` on a fixture results.json: correct, leak and PII counting, and stage tagging.
- [ ] Step 2 to 4: Run, implement, pass.
- [ ] Step 5: Commit `feat(twin): eval harness`.

### Task 9: Hill-climb rounds

- [ ] Round 0: fetch the corpus (seed given on the command line), run a round, score, write REPORT.md.
- [ ] For each round: pick the largest miss stage, make one change (skill text, gate rule, router, build, or presentation), re-run, and keep it only if nothing regresses and PII stays 0. Log the change and the scores.
- [ ] Stop when: lookup ≥95%, relation ≥90%, chains ≥75%, leak-free 100%, PII 0, approvals ≤1 per persona × category, or after 5 rounds. Report what remains.
- [ ] Re-run the grep from Task 7 before each commit.
- [ ] Commit each kept change `fix(twin): <what> (round N)`.
