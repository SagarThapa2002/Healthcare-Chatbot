# Appointment reminders — design notes and current status (Phase 6.2-A)

## Current status: standalone domain foundation, WHAT/WHEN only

`backend/reminder_service.py` and `backend/reminder_config.py` implement the
reminder domain model, eligibility, scheduling, and lifecycle. They are wired
into the live appointment flow at exactly two points -
`chatbot_logic._reschedule_reminders()` (called from `_handle_update_confirm_yes`)
and `chatbot_logic._cancel_reminders()` (called from `_handle_cancel_confirm_yes`)
- and nowhere else. No other part of booking, update, or cancellation is
changed by this slice.

This slice is exclusively concerned with **what** reminder should exist and
**when** it is due. It does **not** send anything: there is no email/SMS
integration, no notification provider, and no new dependency anywhere in this
slice.

## Clinic timezone — explicit, required, fails loudly

`CLINIC_TIMEZONE` (an IANA name, e.g. `"Europe/London"`) is read from the
environment with **no default**. Compared against the alternatives:

- **A required env var with no default** (chosen) — a wrong or missing
  timezone would otherwise silently mis-time every reminder by a fixed
  offset, with no error to ever surface the mistake. That is exactly the
  class of failure `provider_repository.ProviderDataError` and
  `availability_service.AvailabilityError` already exist to prevent for
  their own data; `reminder_config.ReminderConfigError` applies the same
  discipline to timezone configuration.
- **A configurable default** (rejected) — `llm_config.py`'s settings can
  safely default because a wrong value there degrades observably (a bad
  model name errors from the API). A silently-defaulted timezone does not
  degrade observably; it just produces plausible-looking, systematically
  wrong reminder times.
- **A timezone stored per appointment** (rejected for this slice) — would
  require a new appointment schema field and a backfill decision for every
  existing record, including the real legacy appointments already present in
  `appointments.json`, which must not be silently backfilled with an invented
  value. Only relevant if the project ever needs to model genuinely
  multi-timezone clinic locations (`providers.json` already has two
  synthetic `location` values, but neither is timezone-differentiated
  anywhere today).

`reminder_config.get_clinic_timezone()` raises `ReminderConfigError` only
when reminder **scheduling** is actually attempted (inside
`reminder_service.compute_send_at()`) - never at import time, so importing
either module has no effect on the rest of the app. Validated via the stdlib
`zoneinfo.ZoneInfo` (Python 3.11, no new dependency) - which looks up a named
zone from tzdata only and never consults the process's own OS/local
timezone, so this can never silently depend on wherever Flask happens to be
running.

## `sendAt` — stored as UTC, never naive/local

`sendAt` is computed once, at reminder-creation time, and stored as an
ISO-8601 **UTC** timestamp (the same convention `response_model._now_iso()`
already uses for `createdAt`/`meta.timestamp`) - not as a naive clinic-local
string. Algorithm:

1. Parse the appointment's local wall-clock moment from its `date`/`time`
   strings (naive - no timezone yet).
2. Attach the configured clinic timezone.
3. Convert to UTC.
4. Subtract a real `timedelta(hours=24)` **in UTC** - never by subtracting one
   calendar day in local wall-clock time, which is wrong across a DST
   transition. Confirmed with a concrete worked example
   (`test_reminder_service.py`'s DST-boundary test): an appointment at
   `2026-03-30 00:30` `Europe/London` (BST, UTC+1) correctly yields
   `sendAt = 2026-03-28T23:30:00+00:00`; the naive "subtract one calendar
   day locally" approach would have produced `2026-03-29T00:30:00+00:00` -
   30 minutes wrong, because March 28 is still GMT (UTC+0) while March 29-30
   are already BST.

"Is this reminder due?" is therefore always a UTC-vs-UTC comparison,
deterministic regardless of the server process's own timezone.

## Two distinct inequalities, not one

- **At creation**: `sendAt > now_utc` (strict). An appointment whose computed
  `sendAt` is exactly `now` is **not** eligible for a new pending reminder.
- **At due-check**: `now_utc >= sendAt` (inclusive). A pending reminder whose
  `sendAt` has been reached exactly is due, matching ordinary scheduled-job
  semantics (a job scheduled for T is due at T, not only strictly after T).

## Eligibility contract (`is_eligible_for_reminder`)

Required: a non-empty, stable appointment `id` (a legacy record with no id is
**never** eligible - a reminder system needs a stable foreign key, and this
project's own real `appointments.json` currently holds two such legacy
records); a valid `date`; a valid `HH:MM` `time`; the appointment must be
active (`status != "cancelled"`); the computed `sendAt` must be strictly in
the future; no `pending` reminder may already exist for the same
`(appointmentId, type)`.

Not required, not consulted: `providerId`, `durationMinutes`.

"Past appointment" and "less than 24h away" are **the same condition**, not
two separate rules, for the `24h_before` type: since `sendAt = appointment
instant − 24h`, both a past appointment and a less-than-24h-away appointment
necessarily have `sendAt` already in the past. There is exactly one time
check.

## Idempotency

At most one `pending` reminder may exist for a given `(appointmentId, type)`
at any time. A creation attempt while one already exists is a silent no-op -
no error, no duplicate, the existing record is untouched. `sent`, `failed`,
and `cancelled` reminders are terminal, historical records and never block a
new creation for the same pair - see the reschedule-after-sent behavior
below for exactly why.

## Reschedule and cancellation

**Cancellation** (`_cancel_reminders`, called from
`chatbot_logic._handle_cancel_confirm_yes`): any `pending` `24h_before`
reminder for the appointment is transitioned to `cancelled`. Never deleted.

**Reschedule** (`_reschedule_reminders`, called from
`chatbot_logic._handle_update_confirm_yes`, after every successful date/time
mutation - which is unconditional there, since `_handle_update_appointment`
never reaches its `confirm` stage without at least one of `date`/`time`
actually changing): any existing `pending` reminder for the appointment is
first cancelled, then eligibility is re-evaluated against the *new*
`sendAt`, and a fresh `pending` reminder is created if eligible.

**If the previous reminder had already been `sent`** before the reschedule,
there is nothing `pending` to cancel - it is left untouched - and a new
reminder is still created for the new time if eligible. This was a
deliberately-analyzed scenario, not a silent default: the alternative (never
create another reminder once one has been sent) would leave a rescheduled
appointment's new time permanently un-reminded, which is a worse outcome for
a feature whose entire purpose is helping people not miss their appointment.
The result is that `reminders.json` accumulates full, honest history per
appointment (e.g. one `sent` record for the original time, one `pending`/
`sent` record for the new time) - consistent with this project's existing
append-only, soft-delete philosophy (appointments are also never deleted,
only status-flagged).

## Resilience: reminders can never break the appointment lifecycle

`_reschedule_reminders`/`_cancel_reminders` (in `chatbot_logic.py`) wrap
their calls into `reminder_service.py` in a broad `try/except`, logging only
the exception's type name (never its text or any appointment content, per
`backend/LOGGING_NOTES.md`) and otherwise doing nothing further. **This was
not explicitly specified in the approved design and is called out here as an
added implementation decision, not a silent one:** a reminder-scheduling
problem (most likely a missing/invalid `CLINIC_TIMEZONE`) must never prevent
an appointment update or cancellation from succeeding - Phase 6.1's
confirmed-mutation lifecycle is the hardened, load-bearing feature; Phase
6.2-A's reminder foundation is deliberately best-effort on top of it, given
no delivery channel is wired to it yet at all.

One consequence worth noting: only reminder **creation** can raise
`ReminderConfigError` (it is the only operation that calls
`compute_send_at()`). Cancelling reminders and checking which reminders are
due never touch clinic timezone configuration at all - a missing/invalid
`CLINIC_TIMEZONE` therefore only suppresses *new* reminder scheduling; it
never affects existing reminders or the appointment lifecycle itself.

## Persistence

`backend/reminders.json` - a flat JSON array, read fresh on every call,
written back whole - exactly the same convention as `appointments.json`
(`chatbot_logic.py`) and the provider data files (`provider_repository.py`).
No SQLite, no database layer: `backend/db.py`, `backend/models.py`, and
`database/init_db.sql` remain empty placeholders, unused by this or any
other part of the project, and are not activated by this slice.

## Due-reminder query - not a scheduler

`reminder_service.get_due_reminders()` is a pure, callable query: "which
`pending` reminders have `now_utc >= sendAt`". It is not a loop, not a
polling process, not a cron job, not an APScheduler/background-worker
integration. **The trigger mechanism that would call this periodically is
explicitly deferred** - there is no scheduling/cron infrastructure anywhere
in this project today, and introducing one is a separate, later decision.

## Deferred: notification provider abstraction

Not built in this slice. The intended future boundary, matching the exact
pattern `backend/mock_provider.py`/`backend/claude_provider.py` already
establish for the LLM assistant feature (a fixed function signature, a real
provider and a mock provider implementing it identically, selected by an
env-var-driven config with an explicit fail-safe default):

```
reminder_service.py           (decides WHAT/WHEN - this slice)
        |
notification_provider interface:  send(reminder, appointment) -> {"delivered": bool, "category": str}
        |-- mock_notification_provider.py   (not built yet)
        |-- email_notification_provider.py  (a future phase)
        \-- sms_notification_provider.py    (a future phase)
```

Unlike `llm_config.PROVIDER` (which fails safe *toward the real integration*
on an unrecognized value, since answering a question is low-risk), a future
`NOTIFICATION_PROVIDER` setting should fail safe *toward the mock* - a
notification provider that could silently start sending real messages during
local development or tests would be actively unsafe in a way an LLM answer
is not. This is a note for that future phase, not something built or decided
further here.

Note (Phase 6.2-B): the diagram above describes the eventual real-delivery
shape. Phase 6.2-B does not build any of it - instead,
`process_due_reminders()`'s `send` parameter is the seam where a real
provider will eventually be plugged in, simplified to a plain
`bool` return for this slice (see "Due processing" below) rather than the
richer `{"delivered": bool, "category": str}` shape shown above - that
richer shape, and the actual provider files, remain deferred.

## Privacy

A reminder record stores only an opaque `appointmentId` reference - never the
patient's name, date, time, or any medical/symptom content (all of that
already lives in `appointments.json`; a reminder references it, never
duplicates it). No contact address (email/phone) or delivery channel is
stored in this slice, since no delivery channel exists yet to justify storing
one. `failureReason` is a fixed category string, never `str(exception)` -
matching `backend/LOGGING_NOTES.md`'s existing metadata-only logging policy,
applied here to reminder failure records as well as to log lines.

## Due processing (Phase 6.2-B)

`reminder_service.process_due_reminders(send, now=None, path=None, appointments_path=None)`
is the second half of the pipeline built on top of `get_due_reminders()`: it
finds every currently-due `pending` reminder and transitions each to a
terminal state. Still no email/SMS/push, no external delivery, no
scheduler/cron/background worker, and no notification-provider files - see
the deferred section above.

### The `send` contract is deliberately narrow

`send(reminder, appointment) -> bool` is **required** (no default) - there is
no real delivery channel in this slice, so every caller (today, only tests)
must supply an explicit stub. Only a plain `bool` is accepted:

- `True` → `pending` → `sent`
- `False` → `pending` → `failed`, with `failureReason = REMINDER_FAILURE_SEND_FAILED`

`send` cannot supply its own failure category - a deliberate simplification
over the richer future provider shape (`{"delivered": bool, "category":
str}`), to keep this slice's outcomes fully deterministic and
domain-controlled rather than accepting arbitrary strings from whatever gets
plugged in later.

### Appointment existence/active re-check

Before `send` is ever called, the reminder's appointment is looked up fresh
(a new, independently-computed `APPOINTMENTS_FILE` constant in
`reminder_service.py`, mirroring the exact pattern `chatbot_logic.py` and
`availability_service.py` already use for the same file - never an import of
`backend.chatbot_logic`, which would create a circular import):

- appointment missing entirely → `failed`, `failureReason = REMINDER_FAILURE_APPOINTMENT_NOT_FOUND`
- appointment found but no longer active (`status == "cancelled"`) → `cancelled`
- appointment found and active → `send(reminder, appointment)` is called

This is a deliberate **second, independent** safety check, not redundant
busywork: the Phase 6.1 cancellation/reschedule hooks
(`chatbot_logic._cancel_reminders` / `_reschedule_reminders`) already try to
keep reminders in sync, but both deliberately swallow any reminder-subsystem
exception so the appointment lifecycle itself is never blocked (see their own
docstrings) - meaning it's possible, though not expected in normal operation,
for a stale `pending` reminder to survive an appointment's cancellation. Due
processing closes that gap here, cheaply, rather than leaving it
unaddressed. It does **not** re-validate that the reminder's stored `sendAt`
still matches the appointment's *current* date/time (a reschedule-staleness
check) - that remains the reschedule hook's own responsibility; re-deriving
it here would duplicate that hook's logic.

### No timezone dependency

`process_due_reminders()` never touches `CLINIC_TIMEZONE`/`reminder_config`
at all - `sendAt` is already stored as UTC (computed once, at creation
time), so due processing only ever compares UTC to UTC. A missing or invalid
`CLINIC_TIMEZONE` affects only *new reminder creation*; it has zero effect on
due-detection or processing of already-created reminders.

### Persistence: one write per reminder, not one batch write

Due reminders are processed **one at a time**: re-check the appointment,
determine the outcome, save immediately - before moving to the next -
rather than mutating the whole due list in memory and writing once at the
end. This bounds a crash between "identified as due" and "terminal state
saved" to at most one reminder: if the process dies after a successful send
but before that one reminder's save completes, that reminder is simply still
`pending` on disk and will be re-attempted on the next run. This is an
accepted, explicitly-documented at-least-once (not exactly-once) limitation,
of no real consequence today since no real delivery channel exists yet.

### Concurrency

No file locking is added. This is safe under the stated assumption that only
one `process_due_reminders()` invocation runs at a time - true today by
construction, since this slice adds no scheduler/cron/concurrent trigger of
any kind. The remaining, accepted limitation - an unlocked write racing
against a cancel/update hook's own write at the exact same instant - is the
same class of risk already accepted for `appointments.json` and the three
pending-transaction files since Phase 6.1's very first slice.

### Malformed data: fail loudly, not skip

`get_due_reminders()` validates *every* record in the store on every call
(not just due ones), so a single malformed reminder anywhere in
`reminders.json` aborts the whole `process_due_reminders()` run with
`ReminderDataError`, rather than being silently skipped so the rest of the
batch can proceed. This is a real, acknowledged tradeoff (one corrupt record
temporarily blocks every other, otherwise-fine due reminder), chosen for
consistency with this project's existing "fail loudly, never guess" stance
(`ProviderDataError`, `AvailabilityError`, `ReminderDataError` itself) rather
than introducing a new, softer tolerance behavior with no precedent here.
"Mark it failed and continue" was considered and rejected: a malformed
record might not even have a valid `id`/`appointmentId` to safely record a
failure against.

### Idempotency

Guaranteed structurally, not by a separate lock or dedup check:
`get_due_reminders()` only ever returns `status == "pending"` reminders, and
processing immediately flips a reminder's status away from `pending` and
saves before considering the next one - so a reminder is removed from every
future "due" result the instant it's processed. Calling
`process_due_reminders()` again immediately (or at any later time) only ever
sees reminders that genuinely haven't been processed yet.
