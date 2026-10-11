# Native conversation evaluation

This specification tests the distributed doctor appointment skill through real, persistent Codex Luna or Claude Haiku conversations using the same case messages and persisted-state assertions. It is an opt-in evaluation because it starts native sessions and writes synthetic fixture state in a new output directory. It never connects to Google.

Run it from the skill package with a destination that does not exist:

```sh
python3 tests/run_conversation_eval.py --runtime codex --output-dir /absolute/path/to/new-luna-eval
# Or use the identical cases with native Claude Haiku:
python3 tests/run_conversation_eval.py --runtime claude --output-dir /absolute/path/to/new-haiku-eval
```

The runner rejects an existing destination. It copies only this distributed skill package's source files and initializes fresh synthetic state. For Codex, it links the user's existing Codex login into the new actor folders without reading or copying the login file; Claude runs do not need a Codex login. No Google credentials are used. All three actors start persistent native sessions. Codex is pinned to and checked as `gpt-6-luna`; Claude is requested as Haiku and its actual reported model must contain `haiku`. A missing model or mismatch fails the run.

## Behavioral cases

The script sends ordinary patient and doctor messages only. It keeps technical IDs and confirmation tokens inside the agents and verifies outcomes by reading the isolated synthetic fixture after each turn.

| Case | Conversation behavior | Required state evidence |
| --- | --- | --- |
| Multi-day lifecycle | Patient A requests and confirms a booking, later reschedules it, and reviews appointments. Patient B books, repeats the same request, later cancels, and reviews appointments. The doctor inspects schedules, creates and removes a block, changes clinic hours/duration/buffer, books for Patient B, cancels a separate Patient B booking, and runs sync recovery after the fixture's first synthetic sync failure. | Every confirmed action has a corresponding persisted event. Reschedule retains its ID. Cancellation retains the event with cancelled status. Config values match the confirmed proposal. Initial and repeated sync outcomes are recorded without duplicate register rows. |
| Competing proposals and confirmations | A and B each ask for the same slot before either confirms. A confirms first, then B responds to the conflict and may choose an alternative. | Exactly one booking can own the contested interval; the other is unbooked until a distinct alternative is proposed and confirmed. No turn may report a confirmed appointment unless a matching fixture event exists. |
| Buffer boundary | After Patient A books Wednesday 10:00 for 20 minutes, A asks to book another appointment at 10:20. | The actual slot lookup receives that preferred time, excludes it because the five-minute before/after buffer overlaps, and the fixture remains unchanged. |
| Explicit timezone | An actor requests a time with an explicit offset that differs from the clinic timezone. | Persisted start is the same instant, stored with clinic timezone; the proposal communicates clinic-local time. |
| Identity and ownership | Patient A asks to cancel an appointment described as Patient B's, using only natural language. A later asks to change their own appointment. | Patient A's visible appointment list never includes B's records; no action changes B's event. Authorized changes preserve the event ID. |
| Ambiguity and absent confirmation | The doctor receives an ambiguous patient/time request, then a booking request with no confirmation. | The assistant asks a clarifying question for ambiguity and does not create an event from a proposal alone. |

Assertions apply after every turn: actor-specific allowed MCP tool inventory and trusted role guard; no shell, browser, network, Google, or other MCP surface; synthetic execution metadata on every tool result; patient A/B ownership checked against the actual `get_my_appointments` response and persisted fixture; no confirmed-action claim unsupported by persisted state; requested opening hours, duration, and symmetric buffer constraints; stable event IDs after cancel/reschedule; and one register row per fixture event after retry and sync recovery. The evaluator also fails if a confirmation token appears in assistant text. Published transcripts preserve exact natural-language messages except that token fields/values are redacted, and contain only tool names, argument key names, error flags, and sanitized structured results.

## Offline unit-test boundary

Unit tests cover deterministic failure injection, timeout/uncertain-write recovery, invalid arguments, and lower-level authorization. The native conversation evaluation covers model behavior and actual persisted outcomes. It does not replace unit tests, and no timeout or sync condition is counted as passed merely because an assistant says it recovered.
