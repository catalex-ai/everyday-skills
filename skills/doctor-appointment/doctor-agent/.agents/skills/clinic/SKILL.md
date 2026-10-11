---
name: clinic
description: Guide authorized clinic schedule management and reporting.
---
Use authenticated clinic management tools. Review conflicts before blocking or
rescheduling and obtain explicit confirmation. Persist validated configuration
through doctor_configure_clinic. Reconcile reporting with doctor_sync_register;
report failure without undoing Calendar bookings. Never access credentials.
Guide human-owned terminal OAuth actions from README. Synthetic doctor identity
is valid only for practice fixtures. Do not claim real-patient security approval.

Handle ordinary conversational requests; keep tool arguments, IDs and tokens
internal. Ask only for missing patient-facing details and a plain-language
confirmation. Refresh shared availability/schedule after changes by other sessions.

In synthetic-practice mode, confirmations/syncs apply to the local practice
schedule/register only. Never claim a Google write when google_accessed=false.
Speak in patient/clinic terms rather than announcing tools or skills.

Prepare before asking: once the user has supplied the necessary details, call the
requested mutation tool WITHOUT a confirmation token to obtain its validated
proposal and pending token. Only then show that exact proposal and ask the human
once to confirm. Do not ask for confirmation before preparing the trusted proposal.
After a clear yes to that proposal, call the SAME tool with identical arguments
and the saved token in that turn; do not generate another request ID or ask for
another yes. If the details changed or the tool reports a conflict/expired token,
show the new validated proposal and obtain fresh confirmation. Never print,
quote or explain the pending token, raw tool payload, internal IDs or tool names.
A booking request or someone else's confirmation never authorizes a write.
Keep replies short and conversational: answer directly, omit tool-call narration,
and disclose practice mode once per session rather than before every action.
