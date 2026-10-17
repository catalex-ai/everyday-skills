# Clinic agents — golden eval report (2026-10-17)

All agent sessions and the LLM judge ran on **Claude Haiku** (`claude-haiku-5-5`,
verified per turn from each native session's reported model). Every case ran in an
isolated synthetic copy of the package; the live Google configuration was never used.

## Suites

| Suite | Cases | Source |
|---|---|---|
| `tests/scenarios/golden_dataset.json` | 42 (22 patient, 14 doctor, 6 multi-agent) | written for this eval |
| `tests/scenarios/sunrise_suite.json` | 64 (57 runnable, 7 BLOCKED) | the E2E simulation spec, mapped to the real tools |
| `tests/scenarios.json` + `tests/run_conversation_eval.py` | 45-turn E2E script | your existing script |

Runner: `python3 evals/golden_eval.py` (see `evals/README.md`). Live dashboard:
`evals/dashboard.html`. Transcripts are written to `tests/conversations/` (generated, not committed).

## Results: original vs. fixed prompts (same harness, 106 cases each)

| Run | Pass | Warn (judge only) | Fail | Blocked |
|---|---|---|---|---|
| `baseline-final` (original prompts) | 83 | 11 | 5 | 7 |
| `fixed-final` (fixes up to round 5) | 85 | 10 | 4 | 7 |
| retests on final prompts (24 cases ×2, then 10 key cases) | the 4 `fixed-final` fails pass on every retest; retest-3: 10/10 pass | | | |

Your E2E script on Haiku:

| Prompts | Result |
|---|---|
| original | stopped at turn 11/45 |
| final | **PASSED: 45/45 turns, 22/22 final checks**, all actors `claude-haiku-5-5` |

**Single runs are noisy.** Haiku is non-deterministic: E04/E06 failed on the original
prompts in the first baseline and passed in `baseline-final`; P18 passed 2 of 3 retests.
Treat any single pass/fail as one sample. For release gating, run each case 3× (pass@3).

## Agent defects found and fixed

| # | Defect | Agent | Evidence | Fix |
|---|---|---|---|---|
| 1 | Asked "Shall I book/cancel?" before preparing the action, so the user had to say yes twice; once it claimed "I've prepared" without calling the tool | patient + doctor | E04, E06, SD03, script t10/t27 | prepare-first rule + per-turn self-check |
| 2 | Patient B session thought its own booking belonged to another patient and refused (owner `patient-b`) | patient | script t2–6, B02 (original prompts) | identity paragraph: every returned record is this patient's |
| 3 | Asked "additional or move?" for a different time, so a plain yes booked nothing | patient | B10, F04 | only ask when the patient's words imply replacing |
| 4 | Leaked internal ID ("ID a-demo"); hinted at another patient's slot when refusing | patient | P10 | no-ID rule; refusals reveal nothing |
| 5 | Misread clinic-move notice ("moved from 9:00 to 9:30"); re-announced it; prefixed the notice with a label | patient | P18, E02 | previous_start/end semantics; notice must be first characters |
| 6 | Passed bare `"14:00"` as preferred_start, causing tool errors and retries | patient | P19, P21 | explicit argument formats |
| 7 | After a rejected stale confirmation, described the appointment from memory (wrong) and missed the clinic notice | patient | X05 | re-read after any error/conflict |
| 8 | Accepted a typed identity claim ("This is Rahul…") and offered to cancel "your" appointment | patient | N04 | claimed identity is refused, nothing prepared |
| 9 | Chest pain: soft advice ("contact the clinic today") | patient | N05 | emergency line first (112) |
| 10 | Said "confirmed in the Google Calendar" in synthetic mode | doctor | script t19 | never name Google when google_accessed=false |
| 11 | Hours change: did not check affected appointments; implied future-dated settings | doctor | SD06 | list affected appointments in the proposal; settings are immediate |
| 12 | Regression I introduced in the #11 fix: held a confirmed settings change waiting for a decision | doctor | D07, script t13 | yes applies immediately; affected appointments stay booked |
| 13 | Refused to move/cancel appointments whose label is not Patient A/B | doctor | SD03, SD05 | any scheduled appointment can be managed; new bookings stay A/B-only |
| 14 | Named patient without a date: asked for a date instead of looking | doctor | SD10 | scan next 5 working days |
| 15 | Called Monday "tomorrow" | doctor | SD03 | name the date unless it really is tomorrow |

The original prompts are in commit `f8d2828` (see `evals/README.md` to run them
as a baseline). Each run freezes the prompts it tested in
`evals/runs/<run>/agent-snapshot/`.

## Test-data defects fixed (not agent bugs)

- **Your script asked patients for off-grid times.** 3:00 PM and noon, then Tuesday 10:00 for the move. The clinic only offers 9:00, 9:40, 10:20 … slots, so the agent correctly refused and every later dependent check failed. Changed to 3:20 PM, 12:30 PM and 10:20 AM, both in `tests/scenarios.json` and in the final checks.
- **Your checker's buffer check** counted every "10:20 AM" turn after my Tuesday fix. Narrowed it to the Wednesday "another appointment" turn.
- **Your checker's success-claim exemption** used a 50-character window. A correct "already booked … It is confirmed for 12:30" was flagged. Widened to 100.
- **My harness had false positives, all fixed:**
  - tool error results were flagged as "not synthetic"
  - negated claims like "nothing has been booked" were treated as success claims
  - the end of a time range ("10:00–10:30") tripped "never mention 10:30" checks
  - status descriptions ("the appointment is confirmed") were treated as success claims

## Known remaining quality gaps (WARN, judge-flagged; next iteration)

- F03: says "no duplicate rows" based on a row count rather than a row-by-row check. It also opens with "synced" before mentioning that the first attempt failed.
- R06: assumes "replace" without clarifying, and doesn't suggest booking the new slot before cancelling the old one.
- SD09: blames a booking "conflict" instead of saying 7 PM is outside hours with no one-off override.
- SE02: doesn't name the doctor's 2–4 PM time off when explaining why that time is unavailable.
- SE05: offers "book all four" instead of saying recurring bookings are unsupported.
- B02 WARN is a judge error (it read working_days 0 as Sunday).

## Spec requirements not implemented (BLOCKED or adapted; never counted as pass)

- **No messaging/notification adapter (D08, F07, X02).** Patients learn of clinic changes only through the in-assistant notice the next time they open it. Delivery is verified by SD01, SD02, E02 and E05.
- **No doctor→patient proposal/acceptance step (X02, X03).** Doctor changes take effect immediately. X01 and X04 run as adapted versions.
- **No fault injection in native sessions (F01, F02, F08).** Service-level coverage exists in `tests/test_security.py`.
- **One doctor role, no permission tiers (S06).**
- **Only two signed-in synthetic patients, and doctor bookings are limited to A/B.** Priya and Arjun exist only as calendar records.
- **No patient name directory.** The doctor cannot resolve "Ananya" and is told to use Patient A/B.
- **No fixed test clock.** The server uses the real clock, so relative dates resolve against the run date. That date is recorded in each result.
- **Unsupported features:** recurring bookings, variable appointment length, per-appointment hours overrides, future-dated settings.
- **Live Google: NOT RUN** (spec Phase B needs explicit authorization).

## Release note

The prompt edits change 5 files hashed in `references/validation.json`, so
`scripts/verify_package.py` now reports them as changed. The 137 offline unit tests still
pass. Regenerate the receipt as part of your normal release process; I did not.

## Update: count mode, human voice, cleaned prompts

**Count mode (daily patient caps).** New `booking_mode: count` alongside the
default `slots`:
- **Doctor:** sets `daily_caps` (first consultations and follow-ups per day) and
  per-day `day_caps`.
- **Patients:** book a place on a day. Returning patients are treated as follow-ups
  automatically; new patients are asked.
- **Cap reached:** the booking that fills a day immediately records an alert in
  `config/doctor-alerts.json` (for a future WhatsApp connector). The Doctor
  Assistant's next reply leads with it and asks whether to take more.
- **Bookings:** count bookings never block slots or show as conflicts, and are
  transparent in Google free/busy. The doctor can overbook only after saying yes.
- **Tests:** 21 new unit tests (158 total, all passing) and 12 Haiku conversation
  cases (`tests/scenarios/count_mode.json`).

**Human voice.** Both agents now have a "How you sound" section:
- They should read like a receptionist (or a practice manager talking to the
  doctor): short plain sentences, natural confirmation questions.
- No bold text, headings, form labels or "the booking system reports".
- Every eval turn fails on bot formatting, and the judge caps robotic replies
  at 3/5.

**Cleaned prompts.** Both `AGENTS.md` files were rewritten into one organised
rulebook each, and the skills became short checklists. Prompts plus skills went
from 7,461 to about 3,800 words.

| Run (118 cases) | Pass | Warn | Fail | Blocked |
|---|---|---|---|---|
| human voice, before cleanup | 81 | 22 | 8 | 7 |
| cleaned prompts | 89 | 18 | 4 | 7 |

The 4 cleaned-run fails were 3 check issues (since fixed) and 1 real slip (SD09:
"the booking system won't take that time"); a re-run of those and related cases
had no fails. The original 45-turn E2E script passed fully with the human-voice
prompts (45/45 turns, 22/22 final checks).
