# Privacy

Use synthetic data only. This package is not approved for real patient records.
Do not enter diagnoses or medical history. The launcher may pass a patient's
phone and email with their ID; the package stores them only on that patient's
record and shows them only to the Doctor Assistant.
Only scheduling metadata is needed. Patient responses have appointment ID,
start/end, status and kind. Clinic contact/address is configurable administrative
information, not patient contact data.

Each patient's record (the name they give the Patient Assistant, plus any
`short_name`, `phone` and `email` the launcher passed with `--patient-details`) is
kept in `config/patients.json` on this computer. The Patient Assistant sees only
its own patient's name; only the Doctor Assistant sees names, phones and emails
across patients. They never go to the calendar or the spreadsheet.

Practice state is local mock adapter storage under `config/practice-state.json`;
it is not a separate live appointment database. Google Calendar is the intended
live appointment authority. Sheets is a minimal reporting register, with no
patient names, contact information, diagnoses or OAuth credentials. Stable IDs
and timestamps can still be sensitive in live use; restrict calendar/spreadsheet
sharing and agree retention requirements before enabling it.

Refresh tokens are stored exclusively through macOS Keychain. No plaintext
fallback exists. Desktop OAuth client downloads stay outside the repository and
are handled only by the human-owned helper. Avoid shell debugging/tracing during
OAuth. HTTP/API error bodies and traceback details are not passed to the model.
Revocation attempts Google's revoke endpoint and then removes Keychain credentials.

“Local-first” describes configuration, helper and offline fixtures. Native Codex/Claude
terminal conversation/tool results still go to their configured model provider.
Google operations communicate with Google when human-invoked OAuth/access checks
run. CLI session transcripts may persist in each runtime's own storage; native
configuration does not claim to disable all transcript retention.
Do not use real data until provider contracts, retention and access controls are
reviewed and the security blockers are resolved. Clearing synthetic state does
not clear existing model-provider transcripts or Google resources.

The application shares the macOS user's privilege level. Keychain availability
has been checked; separate-process ACL isolation has not. Real-patient mode stays
disabled. See SECURITY.md for measured boundaries.
