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

# Tone hill-climb: jokes, sarcasm, teasing, register

The twin answered jokes as lookups. Asked a pun on the owner's company name
("how many X in <company>?") it said "not sure off the top of my head, let me
check", and it promised to "check and come back" on a grocery errand texted to
the wrong chat. The tone rounds fix that.

Setup: suite `tone` (14 generic chats in `evals/scenarios/tone.json`, plus two
puns per corpus on the owner's own name or work in
`<corpus>/scenarios-tone.json`, outside the repo), three public-figure
corpora, twin and manager on **Haiku**, Opus judge v8 with a new fourth score,
`tone_read`: did it hear what the person was doing (joke, pun, tease,
sarcasm, nonsense, formal, sincere) and answer at that level, in the owner's
own kind of humour. Sincere bad news and a formal invite are controls: a joke
there scores low.

| Round | Change | tone_read | natural | persona | knowledge |
|---|---|---|---|---|---|
| t0 | baseline | 3.77 | 3.90 | 3.31 | 4.48 |
| t1 | twin: "hear them" step (name the tone, a joke is not a lookup), tone moves; `check_reply(tone=...)` flags holding replies to jokes, thanking sarcasm, laughing at sad news, slang in formal replies; manager: writes a "How I play" block (the *mechanism* of the owner's humour) from real messages | 4.21 | 4.02 | 3.56 | 4.44 |
| t2 | twin: errands out of the blue are `nonsense`; let them land their own riddle; no repeated joke; reply in their language mix (Hinglish); nothing after the checked draft | 4.27 | 4.31 | 3.79 | 4.56 |
| t3 | no "ha, fair" concession to a jab; sarcasm with a real question gets the answer, never "let me check". End to end: manager re-extracts voice from scratch | **4.33** | 4.21 | 3.81 | 4.56 |

Means over three corpora, 16 chats each. t0 to t2 differ by one change set
each; t3 re-runs the manager's voice extraction, so it carries that variance too.

What the manager extracts now (one corpus, abridged): "Mostly self-mockery
and exaggeration of his own image... Plays along with an absurd premise, then
adds a dry twist... Answers a friend's jab by roasting back, not by
groaning." For a corpus with little humour it writes "Rarely jokes; mostly
plays it straight", and the twin stays straighter there (lowest tone_read,
4.00), which is the right call.

Known limits: the twin sometimes plays along with a sceptic's exaggeration
instead of correcting it deadpan, and a first name that matches a relative
("Maya") can still be taken for that relative.
