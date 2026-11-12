# Persona features

What a twin needs to sound like its owner rather than a chatbot. Each row
lists who builds the feature, how the manager gets it when the material lacks
it, how the twin uses it, and how the evals measure it. Nothing here is
specific to one owner. Everything is derived from the owner's material and
answers, per persona.

| Feature | Stored as | Built by | When missing, the manager asks | Twin uses it via | Measured by |
|---|---|---|---|---|---|
| Life card: the core of the owner's life, current only | `personas/<p>/card.md`, generated from facts | `build.py` (code) | the CV-style template entries (current role, past roles, education, people, location) | `brief()`, every chat | brain audit `life_coverage`; chat `knowledge_accuracy` |
| People and organisations, grouped by link ("child: A, B") plus their newest facts | card sections | `build.py` from edges | "How do you know X?", "What was your part in X?" | `brief()`, `walk`, `page` | brain audit `life_coverage` |
| Current over outdated | `since` dates; `stale` flag on single-valued links | manager (dates), `build.py` (flag) | conflict questions | search lines marked `older` | scenarios `outdated`, `contradictory` |
| Opinions with reasons and dates | items `kind=opinion` | manager | `opinions`, `opinion_changed`, `values` | `search` | brain audit `soul_quality`; chat `persona_fidelity` |
| Stories the owner tells | items `kind=story` | manager | `stories` | `search` | brain audit `soul_quality` |
| Real messages, verbatim, paired with the message they answer | items `kind=example`, `context` = "<who> says: <their message>"; `examples/` index | manager: `import_messages` for chat exports and interviews; `answer` on a reply question | "How would you reply?" questions (`reply_family`, `reply_friends`, `reply_peers`, `reply_seniors`, `reply_public`, and the manager's own follow-ups via `ask_reply`) | `examples(q, who)`: pairs to the same kind of person, two on topic plus a spread, with their typical length; about 6 anchors in `brief()` | `ledger.py` (pairs, audiences, verbatim share); brain audit `voice_quality`; chat `naturalness` |
| Register per kind of person (case, length, warmth with a friend vs an investor) | the audience words in each example's `context` | manager (writes who the message was to) | the `reply_*` questions, one audience each | `examples(q, who)` and `check_reply(draft, msg, who)` rank messages to the same kind of person first | chat `persona_fidelity` (register) |
| Measured texting style (length, case, emoji, laugh, openers, phrases) | `style.json` | `style.fingerprint` (code) | (comes from the examples) | `brief()` voice section; `check_reply` limits | the `tells` counts in the eval report |
| Voice habits, as tendencies with frequency and setting | `voice.md` | manager (`write_persona_text`) from examples | (rewritten after new examples) | `brief()` | brain audit `voice_quality` |
| Soul: values, how they decide, what they won't do | `soul.md` | manager from opinions and stories | `values` | `brief()` | brain audit `soul_quality` |
| Rules for kinds of question (time, personal money, commitments) | `rules.md` | owner, via the manager | (corrections) | `brief()` | scenarios `logistics`, `trap` |
| Who may know what | category rules per persona | owner answers approval questions | approval questions | builds only the allowed items | chat leaks; brain audit `privacy` |
| Questions the twin could not answer | `inbox.jsonl`, then `asked` questions | twin `ask_owner`, manager | "X asked your twin ..." | (the answer becomes items next time) | `asked_owner` count |
| Reply hygiene: no refusals, misplaced "let me check", assistant phrasing, markdown, run-on length | (code) | `style.check` | | `check_reply(draft)` | chat `naturalness`; `tells` counts |

## Which gap gets which reply (twin skill)

| The gap | Reply |
|---|---|
| Private for this audience | A warm dodge, never pretending not to know |
| A detail of the owner's past that memory lacks | What memory supports, then a light line, never invented |
| A new plan, document, number or commitment | "Let me check and get back to you", plus `ask_owner` |
| Their routine or status (hiring, raising, how something went) | Answer; that's not a commitment |
| An unclear reference | Ask which one |

## The eval loop (`evals/stages.py`)

1. **Twin on the right data.** Opus builds the brain and the Haiku twin
   chats. This isolates twin and skill quality.
2. **Manager.** `brain_audit.py` scores the brains built by the Haiku and Opus
   managers on life coverage, accuracy, voice, soul and privacy, and lists
   what is missing.
3. **End to end.** Haiku manager plus Haiku twin, from scratch.

With `--interrogate N` the simulated owner keeps answering after the sources
are in, until N answers in all: mostly "How would you reply?" questions, each
followed by a follow-up the manager queues. With `--owner-noise 0.15` about
one answer in seven is lazy, garbage, skipped, rambling or full of typos
(chosen by a hash of the question id, so runs repeat). Junk is dropped by the
tool; lazy but real replies are kept, since that is how people text.
`ledger.py` records what each run collected: kinds, real messages per
audience, conversation pairs and how many are verbatim real.

Chats are scored by an Opus judge on knowledge accuracy, persona fidelity and
naturalness, always reported separately. The judge is deliberately harsh: 5
means a close friend would not suspect anything.

**Calibration** (`evals/calibrate.py <corpus> [run]`) grades the owner's real,
held-out answers with the same judge. Real answers must score high and an old
twin run low, or the judge is measuring the wrong thing. Judge v3 (synthetic
founder): real answers P 4.33, N 4.75; the first twin run P 2.00, N 2.17.
