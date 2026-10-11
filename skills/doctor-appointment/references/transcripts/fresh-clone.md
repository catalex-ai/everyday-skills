# Fresh public-clone launch check

Eight actual turns on Codex Luna and Claude Haiku. Synthetic records only; no Google calls. The last two turns check the patient-label refinement.

## Codex — Patient

**User**

Book me an appointment on Tuesday, October 13 at 2:00 PM.

**Assistant**

I’ll check availability for October 13 at 2:00 PM in the clinic’s timezone, then prepare the exact appointment proposal.
This is a practice appointment. I’m checking October 13 at 2:00 PM in the clinic’s Asia/Kolkata timezone.
I can book Tuesday, October 13, from 2:00 to 2:30 PM in the clinic’s Asia/Kolkata timezone. Shall I confirm this practice appointment?

## Codex — Patient

**User**

Yes, please.

**Assistant**

Your practice appointment is confirmed for Tuesday, October 13, 2:00–2:30 PM, Asia/Kolkata time.

## Codex — Doctor

**User**

Show me the appointments for Tuesday, October 13.

**Assistant**

I’ll check the current schedule for October 13 in the clinic’s configured timezone.
There is one confirmed practice appointment on Tuesday, October 13, from 2:00 to 2:30 PM. The schedule is in the clinic’s configured timezone.

## Claude — Patient

**User**

Book me an appointment on Wednesday, October 14 at 2:00 PM.

**Assistant**

This is a practice booking, so it only affects the local practice schedule. No Google Calendar or Sheets records are changed.

I can book this:

- **Wednesday, October 14, 2026, 2:00 PM to 2:30 PM** (clinic time, India Standard Time)

Should I go ahead and book it? Please reply yes or no.

## Claude — Patient

**User**

Yes, please.

**Assistant**

Your practice appointment is confirmed for **Wednesday, October 14, 2026, 2:00 PM to 2:30 PM** (clinic time, India Standard Time).

## Claude — Doctor

**User**

Show me the appointments for Wednesday, October 14.

**Assistant**

Wednesday, October 14 has one appointment:

- **2:00 PM to 2:30 PM**, Patient A, confirmed

Times are in the clinic's timezone (UTC+05:30). This is practice mode, so the change only affects the local practice schedule, not Google Calendar.

## Codex — Doctor

**User**

Show me the appointments for 2026-10-13.

**Assistant**

I’ll check the current schedule for 13 October in the clinic’s timezone.
There’s one appointment on 13 October: **Patient A, 2:00–2:30 PM, confirmed** (clinic time). This is a practice schedule; Google Calendar wasn’t accessed.

## Claude — Doctor

**User**

Show me the appointments for 2026-10-13.

**Assistant**

Tuesday, 13 October 2026 has one appointment:

- **2:00 PM – 2:30 PM** (clinic time, +05:30): **Patient A**, confirmed

No blocks are listed for that day. This is the practice schedule, so nothing was checked against Google Calendar.

