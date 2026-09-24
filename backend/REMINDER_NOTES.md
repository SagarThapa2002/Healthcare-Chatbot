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
        |-- mock_notification_provider.py   (6.2-A's own testing precedent - not built yet)
        |-- email_notification_provider.py  (Phase 6.2-B)
        \-- sms_notification_provider.py    (Phase 6.2-C)
```

Unlike `llm_config.PROVIDER` (which fails safe *toward the real integration*
on an unrecognized value, since answering a question is low-risk), a future
`NOTIFICATION_PROVIDER` setting should fail safe *toward the mock* - a
notification provider that could silently start sending real messages during
local development or tests would be actively unsafe in a way an LLM answer
is not. This is a note for 6.2-B, not something built or decided further
here.

## Privacy

A reminder record stores only an opaque `appointmentId` reference - never the
patient's name, date, time, or any medical/symptom content (all of that
already lives in `appointments.json`; a reminder references it, never
duplicates it). No contact address (email/phone) or delivery channel is
stored in this slice, since no delivery channel exists yet to justify storing
one. `failureReason` is a fixed category string, never `str(exception)` -
matching `backend/LOGGING_NOTES.md`'s existing metadata-only logging policy,
applied here to reminder failure records as well as to log lines.
