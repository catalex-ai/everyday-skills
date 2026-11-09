# Digital twin: design

Status: approved in conversation 2026-11-09 (v2 page plus the changes below).
Review page: https://claude.ai/artifact/9Rt2wUbhpnt1yWrMB4XS8h

## Intent

A personal brain built from two local agents that share one folder.

- **Twin manager** (privileged). The owner talks to it. It reads files and links,
  strips PII, splits material into small facts, files each fact under a
  category, keeps personas, asks the owner questions, takes corrections, tidies
  and audits.
- **Twin** (read only). Other people talk to it. It answers as the owner, using
  the active persona that the manager chose, through four read tools. It does
  not know or choose its persona.

It is a hobby project for one person. It is not a product. Everything runs
locally.

## Goals

1. Start from a CV, a profile export or a link, then grow from the owner's
   answers.
2. **Approval by type, never by item.** The manager asks "may <persona> know
   <category>?", never "may I add this fact?". A rule, once given, applies to
   every past and future fact in that category. Facts in approved categories
   go straight in. Only facts in categories that have no rule for a persona
   wait, and each such category produces a single question.
3. Questions never block. Material is always stored. Anything waiting on an
   answer waits in raw, and the rest flows on.
4. Raw material is always kept (redacted), so adding a persona later replays
   everything into it, and only the categories that persona has no rule for
   produce questions.
5. Several personas (for example professional or personal). The manager
   creates them, sets their rules, and sets which one the twin uses.
6. Proactive information questions: gaps against a template, the graph and
   contradictions generate the next best question.
7. Corrections ("you said X, it should be Y") go to the right place: voice,
   reply rules, a fact, a category rule, the template, or the soul.
8. Answers to relationship chains ("A of B of C") come from a graph walk.
9. Audit in a browser via a generated static HTML page.

## Non-goals

- Transport (WhatsApp, relay). That comes later and calls in.
- Hosting, accounts, a vector database, Docker.
- Voice.

## Anti-goals

- PII on disk: no email, phone, street address, postcode, ID numbers, personal
  URLs or handles, date of birth, or pay amounts, in any zone, raw included.
- Per-item approval prompts.
- Any named person, role or domain hardcoded in the skill, prompts or
  templates. The test subject's name appears only as an eval command-line
  argument and in gitignored downloaded data.
- The twin reading anything outside its persona folder.

## Data model

`~/.twin/brain/` by default (`TWIN_HOME` overrides it). It is never inside the
repo.

```
brain/
  raw/                      manager only. Always kept.
    sources/<sid>.md        redacted source text (gate-checked), first line = origin
    items.jsonl             every fact ever extracted (append and update by id)
  policy/                   manager only
    categories.json         category vocabulary the manager writes: slug, description
    rules.json              {persona: {category: "allow"|"deny"}}; missing = unreviewed
    dictionary.json         relation vocabulary: name, inverse/symmetric, words, aliases
  personas/<slug>/          the manager writes; the twin reads only the active one
    contract.md             audience, include, exclude (plain words)
    soul.md voice.md rules.md
    facts.jsonl             allowed items only (generated)
    graph.json              allowed edges only (generated)
    pages/<entity>.md       generated, one per entity, Now line first
    index.md profile.md     generated
    index.sqlite            FTS5 + vectors (generated, safe to delete)
  active                    one line: the persona slug the twin uses
  questions.json            open, answered, declined, snoozed
  ledger.json               conflicts and what lost
  log.jsonl                 every write
  corrections.jsonl
  schema.yaml               what a complete profile means (types, fields, weights)
  privacy.yaml              PII rules (copied from the template, editable)
```

**Item** (one fact):

```json
{"id":"f-…","text":"I studied economics at Hansraj College.",
 "about":"me","category":"education",
 "edge":{"s":"me","rel":"educated_at","o":"Hansraj College"},
 "src":"s-…","since":"1988","conf":"high","by":"doc|you"}
```

`text` is a whole sentence, written the way someone would ask about it. `edge` is
optional. The `id` is derived from the text, so it is stable.

**Persona build is deterministic.** `rebuild(persona)` selects the items whose
category is `allow` for that persona, then writes facts.jsonl, graph.json,
pages, index.md, profile.md and index.sqlite. No model is involved. Leak-free
follows by construction: a denied or unreviewed item is never written into a
persona folder.

## Flows

**Add.** The manager reads the material (raw is in model context only), redacts it
and calls `add_source(text, origin)` → gate → `raw/sources`. It extracts items
and calls `add_items([...])` → gate → `raw/items.jsonl`. New categories are
declared with `define_category`. Then `sync()`:

- for each persona × category in the new items: `allow` → rebuild includes it;
  `deny` → skipped; missing → one approval question
  (`kind: approval, persona, category, waiting: n, examples: 2 item texts`)
- information-gap questions are refreshed

**Answer.** `answer(question_id, text)`. An approval answer sets the rule, so the
waiting items flow into the persona on the same call. An information answer
goes through add.

**New persona.** `create_persona(slug, audience, include, exclude)` → every
category in raw that has no rule for it becomes a single approval question.
The manager may pre-fill rules from the contract (`set_rule`) when the
contract is unambiguous, so the owner is only asked about real unknowns.

**Activate.** `set_active(slug)` → `brain/active`. The twin's read server reads it
on every call.

**Correct.** `record_correction(said, should, scope)` → the manager routes it to
voice, rules, an item (`by: you`), a category rule, the schema or the soul.

**Tidy.** Merge duplicate entities through aliases, resolve contradictions into
questions, fold three or more similar voice examples into a rule, and archive
superseded items (`status: superseded`, never deleted).

## PII gate

`gate.check(text) → [findings]`, run by every write tool before disk. A finding
gives a type and position only, never the value. It is regex and code: email,
phone (international and local), URL and handle, postcode, ID-like digit
runs, a full date of birth near "born", and money near pay words. Rules live in
`privacy.yaml`. On a finding the write is refused and the manager must redact.
`audit` re-runs the gate over the whole brain.

## Read path

Read server `mcp_read.py` (stdio) has tools: `search(q)`, `walk(q)`, `page(name)`,
`profile()`, `brief()` (soul, voice and rules of the active persona). It opens only
`personas/<active>/` and SQLite with `mode=ro`.

The router (from tweety, measured there) adds the graph walk only when the
question names a graph entity other than `me`, uses a relation word from the
dictionary, or asks about connections (how many, who else, the same … as, how is
… connected). A walked answer is restated in the question's words ahead of the
supporting facts.

Search is hybrid: FTS5 BM25 plus model2vec cosine (potion-base-8M), merged by
reciprocal rank. If model2vec is missing it falls back to BM25 only.

## Questions

`questions.json` entries: `{id, kind: approval|info|conflict, persona?, category?,
about?, field?, text, score, status, asked, created}`. `next_questions(n)` returns
the top n open ones, approval and conflict first (they unblock items), then info
gaps by score:

score = gap weight × section weight (schema.yaml) × 0.5^times_asked

| gap | weight |
|---|---|
| required field empty | 1.0 |
| contradiction | 0.9 |
| claim without evidence (conf low) | 0.7 |
| entity mentioned, no page facts | 0.6 |
| person with no edge to me | 0.6 |
| stale (> 12 months) | 0.3 |

The manager words the question. The engine supplies the slot and anchor facts.

## Layout in the repo

```
skills/digital-twin/
  SKILL.md README.md PRIVACY.md TESTING.md
  manager-agent/CLAUDE.md  manager-agent/.claude/skills/twin-manage/SKILL.md
  twin-agent/CLAUDE.md     twin-agent/.claude/skills/twin-reply/SKILL.md
  brainkit/  store.py gate.py ids.py graph.py search.py router.py questions.py
             build.py audit_html.py mcp_manage.py mcp_read.py cli.py
  templates/ schema.yaml privacy.yaml soul.md voice.md rules.md contract.md
  evals/     fetch_corpus.py fetch_pii.py make_qa.py run_round.py
             simulate_owner.py score.py REPORT.md
  tests/
```

Dependencies: `mcp`, `model2vec`, `PyYAML`. Python ≥ 3.11. A venv lives inside the skill folder.

## Hill climbing

Corpora are downloaded to `~/.twin-corpora/` and never committed:

- **Public-figure corpus**: a seed Wikidata id given on the command line.
  Wikipedia articles for the seed and its neighbours over personal and
  professional relations, plus `truth.json` of Wikidata facts. The seed's own
  article is split into sections, which become separate sources fed in batches.
  Some sections are held back as "in the owner's head" for the simulated owner.
- **PII probes**: `ai4privacy/pii-masking-200k` rows with labelled spans, mixed
  into the input stream.

Generated from truth (no model): lookup, relation, multihop, aggregate and
path questions, each tagged with the persona expected to know it and the
persona that must not.

Simulated owner (eval only): answers approval questions from an eval-side
description of what each persona may know, and information questions only from
held-back text, or says "don't know".

Metrics per round:

- correct and evidence found, by question kind and persona
- leak-free per persona (must-not answers absent from reply and folder)
- PII spans on disk: must be 0
- approval questions asked per category (must be ≤ 1 per persona × category,
  never per item)
- question yield: held-back facts captured per info question

Each miss is tagged with a stage: not extracted / wrong category / no edge /
not retrieved / retrieved but answered wrong / leaked. Change one thing,
re-run, keep it only if no metric regresses and PII stays 0. Log each round in
`evals/REPORT.md` without naming the subject.

Models: configurable. In evals the manager runs via `claude -p` (default
sonnet) and the twin via `claude -p` with only the read MCP tools (default
haiku).

## My calls (to check)

- Raw is kept but redacted. That makes the PII anti-goal hold for raw too.
- A persona build is deterministic from items, with no model at fold time. This
  makes replay into a new persona cheap and makes leaks impossible by
  construction.
- Other people's names in public contexts are stored as entities, with no
  contact details. Whether a persona may know about family members is a
  category rule.
- Work metrics are kept. Pay is not.
- Approval and conflict questions rank above information questions.
