# Hill-climb report

Both agents (manager and twin) and the simulated owner ran on **Haiku** in every
round. Each round starts from an empty brain. The manager ingests the corpus in
batches, answers its own approval and information questions through the
simulated owner, then the twin is asked the eval questions once per persona.

Corpus: one public figure's encyclopedia pages plus structured facts (the
"subject"), and synthetic PII notes. The subject is used only for testing; no
name, role or field of work appears anywhere in the skill.

Personas (evals/personas.json): **professional** (work only; family, homes,
health, money and contact details excluded) and **personal** (everything except
credentials).

## Results by round

"Grounded" counts only questions whose answer the documents state and agree
with. Excluded (truth from the structured source disagrees with or goes beyond
the documents): awards (exact list), companies owned, positions held,
organisations founded, the spouse's job, the country of home or birthplace
(the twin rightly refuses to add a country no document names), and the mother's
father. Raw numbers for every kind are in each round's `results.score.json`.

| Round | Change tested | Personal grounded | Professional grounded | Professional leak-free | PII on disk | Repeat approvals |
|---|---|---|---|---|---|---|
| 0 | first run | 0 (owner answers empty, everything waiting) | - | - | 0 | - |
| 1 | prompts on stdin, rules preset when categories appear | low (multihop 1/15) | 5/12 | 84% (6/38) | 0 | 0 |
| 2 | split mixed facts, close people get own facts, quieter twin | multihop 5/13 | 6/8 | 97% (1/36) | 0 | 0 |
| 3 | mixed-fact lint + `replace_item`, grounded QA set | 14/15 | 3/3 | 100% | 0 | 0 |
| 4 | twin stays in voice, partial answers | 15/15 | 3/3 | 91% (2/23) | 0 | 0 |
| 5 | hide facts about relatives a persona cannot see | 14/15 | 3/3 | 100% | 0 | 0 |
| 6 | eval asks in second person ("your kids") | 12/15 | 3/3 | 100% | 0 | 0 |
| 7 | "you/your" mean the owner, relation-pair direction | 14/15 | 3/3 | 96% (1/23) | 0 | 0 |
| 8 | dictionary words beat name guesses; any hidden link hides the person | **15/15** | **3/3** | **100%** | **0** | **0** |

Twin voice breaks (mentions of tools, "the twin", "records", answering as an AI):
about 5 of 62 replies in round 3, 1 of 62 in round 8.

## What each round found

- **R0** The simulated owner's prompt was swallowed by a variadic CLI flag; and
  personas were made before any categories existed, so no rule was preset and
  every fact waited. Fix: prompts on stdin; `define_category` returns personas
  with no rule yet and the skill sets them at once.
- **R0** Changing a PII type from hold to drop left old held values in the
  SQLite file bytes. Fix: demote tokens, delete held rows, `secure_delete=ON`.
- **R1** Work facts carried family details ("…with my wife"). Fix: one fact,
  one type of information; then a code lint (`check_mixed`) and `replace_item`.
- **R1** The graph walk failed on plurals, verb forms and unknown words. Fix:
  stemming, relation names as words, leftover-word handling, counts.
- **R2** Many misses were facts no document states. Fix: the eval keeps only
  questions whose answer appears in the corpus text.
- **R4** Facts about the children were filed under work-like categories and
  reached the professional persona. Fix in code: a person whose link to the
  owner is hidden from a persona has their own facts withheld, whatever
  category they were filed under.
- **R5** Questions said "my children", but the twin talks to other people and
  sometimes read it as the asker's children. Fix: the eval asks the way others
  would ("your children"); the twin reads both.
- **R6** "you/your" were not read as the owner in the graph; a manager-written
  relation pair with clashing words flipped "children" into "parents"; an empty
  walk told the twin to refuse even when search had the answer. All fixed in
  code with tests.
- **R7** A guess from a relation's name ("child_of") outranked the dictionary's
  own words; and a child who is also a co-worker reached the professional
  persona through the work link. Fix: stated words beat name guesses; any
  hidden link hides that person's own facts.

## Known limits

- Manager recall varies between runs: in round 7 it did not record where the
  owner lives, in round 6 it did. Same documents, same model.
- The subject is famous, so Haiku's own knowledge can leak into answers. The
  twin's rules forbid it, and a real owner will not be famous, but the leak
  score on this corpus is a little pessimistic for that reason.
- Only one path question survives the grounding filter: the downloaded pages
  are short. Relationship chains are tested mostly through multihop questions.
- With 31 questions, one question moves a row by 3 to 14 points. Read the
  table as trends.

## Reproduce

```
.venv/bin/python evals/fetch_corpus.py --seed <WIKIDATA_QID> --out ~/.twin-corpora/subject-a   # see evals/README.md
.venv/bin/python evals/run_round.py --corpus ~/.twin-corpora/subject-a --round N --questions 30
```
