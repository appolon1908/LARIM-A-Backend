# Job requirements, evidence and time

Administrators PUT `/api/v1/admin/catalog/{service_id}/job-policy` with `items` (up to 50 unique codes,
labels and requires_evidence flags) and `require_time_entry`. The operation is permission-protected,
idempotent and audited. Each update increments the policy version.

Quote creation copies the policy into the quote snapshot. Booking acceptance retains that snapshot;
changing the current catalog policy cannot weaken or add requirements to a previously quoted job.
Bookings created before this policy feature retain their original behavior with no implicit new requirements.

Assigned approved providers GET `/provider/jobs/{booking_id}/checklist` and PUT individual items at
`/provider/jobs/{booking_id}/checklist/{code}` with completed, evidence_id and optional notes. Updates
require IN_PROGRESS and an Idempotency-Key. Evidence must belong to the same job and provider. The
customer UI cannot satisfy a provider checklist by sending arbitrary status values.

Evidence upload remains private and quarantined. An independent administrator with `job.evidence.review`
POSTs `/admin/jobs/evidence/{document_id}/review` with CLEARED/REJECTED and a review reason. Reviews are
audited; reviewers cannot clear their own uploads. This is an explicit manual review workflow, not a
claim of automated malware scanning. Review and completion use the same booking-first lock order so a
review cannot race payment capture. Finalized jobs do not allow retrospective evidence status changes.

POST `/provider/jobs/{id}/time/start` and `/time/stop` use server UTC timestamps. A partial unique index
prevents multiple open clocks; the booking lock serializes time changes and completion. GET the bounded
`/provider/jobs/{id}/time` history. Retries with the same idempotency key return the same entry.

Before COMPLETED or payment capture, the domain application validates all snapshotted checklist items,
cleared evidence where required, no open clock, and a positive closed time interval when required.
Failure returns 409 and preserves the booking/payment state. Integration tests exercise every rejected
completion, policy changes after quoting, wrong-provider access, evidence review, duplicate clock start,
and successful completion/capture after requirements are satisfied.

Paid job extras still require their own customer-approved financial workflow; this implementation does
not let a provider silently change the immutable original booking price.
