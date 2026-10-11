# CatalEx verified identity integration contract

No gateway code was present in the supplied workspace. This is a contract, not
an implemented live authentication integration. No gateway URL, signing secret
or OAuth credential is accepted as a model-generated tool argument.

A future trusted broker must deliver a verified session context out of band:

```json
{
  "version": 1,
  "issuer": "configured-catalex-gateway",
  "audience": "doctor-assistant-trusted-broker",
  "subject": "opaque-authenticated-subject",
  "role": "patient",
  "clinic_id": "authorized-clinic",
  "session_id": "opaque-session",
  "issued_at": 1791720000,
  "expires_at": 1791720300,
  "nonce": "single-use-random-value"
}
```

The broker validates signature using pinned gateway keys, issuer/audience,
expiry/not-before, nonce/replay protection, subject/clinic membership and role
against gateway authentication evidence. Transport must authenticate the gateway
(mTLS or authenticated local IPC with restrictive OS permissions), outside Claude's
read/tool surface. Reject missing/expired/invalid context. Do not accept unsigned
JSON or bearer tokens from chat. Bind immutable `Identity` to a session-specific
narrow dispatcher only after broker verification. Do not let callers construct
`verified=True` themselves in a network endpoint.

Doctor context requires clinic membership and an appropriate authenticated doctor
session, preferably with step-up authentication for management. Google app OAuth
is separate: it grants Google resource access, not doctor/patient identity. Human
confirmation must arrive from an independently authenticated user channel with an
action digest and expiring, single-use receipt; model-visible confirmation tokens
alone are insufficient. Confirmation receipts cannot be issued by the model.

Before live use, deploy the broker under an OS credential boundary that excludes
Claude and the patient process from refresh tokens, its signing material, service
code/config writes and credential-store access. Expose only the narrow patient
or doctor socket appropriate to the verified identity. Never send gateway secrets
to MCP environment or Claude. Re-audit actual interactive CLI tools and OS denial
probes. Complete consented Google tests on dedicated synthetic resources.

The public operation inputs remain those in `tools/core.py::ARGUMENTS`.
There is deliberately no subject, role, clinic, endpoint, credential, arbitrary
query, filesystem path or executable field. Reject unexpected keys. Patient
Calendar retrieval must use the composite ownership scope; doctor schedule
retrieval requires the authorized clinic. Calendar private metadata is controlled
by trusted helpers and authorized calendar administrators, never patient text.

Acceptance: Patient A cannot list/read/change B by guessing an ID, indirect event
instructions cannot affect policy, patient cannot connect to doctor broker methods,
expired/replayed assertions fail, revocation terminates sessions, secrets are
unreadable from patient and doctor model runtimes, independent confirmation is
required for writes, and real Calendar/Sheets tests succeed before removing the
hard live gate in reviewed code. No appointment database is needed.
