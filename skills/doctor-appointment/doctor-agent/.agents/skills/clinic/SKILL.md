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
