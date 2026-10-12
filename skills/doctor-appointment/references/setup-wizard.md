# Clinic setup wizard contract

Use this for initial setup and for resuming an existing installation. Preserve
existing appointments, selected resources and credentials; never reset practice
state or create a replacement register merely to repair setup.

## Readiness before consent

Inspect non-secret installed configuration, actual MCP backend, secure credential
storage availability, trusted doctor/patient identity support and effective role
permissions. An existing Google connection is not evidence of a live backend.
This release has only PracticeRuntime in its agent server and a live-write gate;
report that blocker before asking for Google consent. Do not remove that gate to
complete the wizard. Connection-only setup is available on explicit request.

## Conversation when live support is available

1. Ask clinic name and hours, retaining existing answers. Gather timezone (default
   Asia/Kolkata), duration, buffers, breaks and contact details only as needed;
   persist through validated trusted configuration operations.
2. Reuse an existing valid Google connection. Otherwise explain briefly that a
   browser will open to connect Calendar and Sheets, and obtain authorization to
   begin. Launch the trusted helper; the doctor signs in and approves access.
3. List writable calendars by name and ask which to use. Keep IDs internal.
4. Ask “Create a new appointment register, or use an existing spreadsheet?”
   For new, ask its title; for existing, accept its normal URL. Explain setup will
   create/initialize owned register worksheets before performing those writes.
   Both appointment sessions lack spreadsheet-creation tools.
5. Verify selected resources and required granted scopes. Automatically select the
   Google backend for both roles once readiness checks pass. Reload/reconnect
   sessions if required; no extra “switch to live” question and no manual edits.
6. Verify the running backend and live reads. Report setup complete only after
   these succeed. An empty real calendar is valid; do not populate it with mocks.
   Creating any test appointment requires separate explicit consent.

A publisher-owned Desktop OAuth registration can remove per-doctor Cloud Console
work. The current bundle does not supply one. If none is configured, explain this
publisher prerequisite once; do not pretend a consent URL alone completes OAuth
or automatically create a project in the doctor's account. The documented private
client-file fallback remains available for users who explicitly choose it.

## Failure and resumption

Missing client, denied scopes, unavailable secure store, unresolved identity or
runtime audit, and failed backend activation are blockers. Report the specific
problem and retain completed non-secret progress. Do not silently downgrade to
practice after consent. If Google becomes unavailable in an activated session,
return an availability error; do not redirect bookings into local fixtures.

## Acceptance scenarios for a future live implementation

- First setup asks short questions, completes browser consent and selects resources
  by name/URL; both running roles use the selected Google adapters automatically.
- Valid existing authorization skips repeated consent and preserves appointments.
- Empty Google resources return empty results without seeded practice records.
- Failed activation reports incomplete setup without any mock booking success.
- Explicit offline practice never accesses Google or shares records with live mode.
- Patient ownership and doctor clinic authorization remain enforced after activation.
- Creating a synthetic live appointment requires independent consent and confirmed
  Calendar readback; Sheets failure never reverses a successful Calendar write.

These are acceptance requirements, not claims that this release passes live tests.
