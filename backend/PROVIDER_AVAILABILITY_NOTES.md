# Provider & availability — design notes and current status (Phase 6.1, Slice 1)

## Current status: standalone foundation, NOT wired into the live chatbot

`backend/provider_repository.py` loads and validates `backend/providers.json`
and `backend/provider_availability.json`. Nothing in `chatbot_logic.py`,
`webhook.py`, or the frontend imports or calls this module yet - booking,
update, cancel, and view behavior are completely unchanged by this slice.
This is intentionally a small, isolated data foundation for a later slice to
build the actual booking-flow integration on top of.

## Recurring weekly availability only

Every entry in `provider_availability.json` describes a **recurring weekly**
window: a provider is available on a given `dayOfWeek`, from `startTime` to
`endTime`, in `slotMinutes`-sized slots, every week, indefinitely. There is
no concept of a specific calendar date in this file - only a day-of-week
name.

## Calculated slots come in a later slice

This slice deliberately does **not** include a slot-generation function.
`get_provider_availability()` returns the raw recurring windows only (e.g.
"Mondays 09:00-17:00 in 30-minute slots") - it does not expand that into a
concrete list of bookable date/time slots, and it does not cross-reference
`backend/appointments.json` to see which slots are already taken. Both of
those are explicitly out of scope here and belong to a later slice.

## Demo times are local clinic time - no timezone conversion

Every `startTime`/`endTime` in `provider_availability.json` is plain
`HH:MM` local clinic time, with no timezone attached and no conversion
performed anywhere in `provider_repository.py`. This matches
`backend/appointments.json`'s existing `date`/`time` fields, which are also
plain, timezone-less strings. This is a deliberate scope limitation for a
synthetic/demo project, not an oversight - see the Phase 6.1 architecture
report for the reasoning.

## No holiday/exception-date support yet

A provider's weekly schedule applies uniformly to every occurrence of that
weekday - there is no way to mark a specific date as unavailable (a holiday,
a one-off closure, etc.) in this slice. Adding that would mean introducing a
second, date-specific override concept alongside the recurring weekly one,
which is deliberately deferred to a later slice to keep this foundation
small.

## Synthetic/demo data only

Every provider name in `backend/providers.json` (e.g. "Dr. Patel", "Dr.
Nguyen", "Dr. Okafor") is a generic, synthetic placeholder - not a real
clinician, and not linked to any real clinic. This matches the same
synthetic-data policy already documented for LLM assistant testing in
`backend/LLM_ASSISTANT_NOTES.md`.

## Validation - fails loudly, never silently

`provider_repository.ProviderDataError` is raised (never silently
swallowed, coerced, or partially accepted) for:

- a missing or unreadable data file, or invalid JSON
- a non-list top-level value in either file
- a provider missing a required field (`id`, `name`, `specialty`,
  `location`), or one that isn't a non-empty string
- a duplicate provider `id`
- an availability entry referencing a `providerId` that isn't a real,
  known provider
- an invalid `dayOfWeek` (must be a full English weekday name, e.g.
  `"Monday"`)
- a malformed `startTime`/`endTime` (must be `HH:MM`, 24-hour, zero-padded)
- `startTime` that is not strictly before `endTime`
- a `slotMinutes` that isn't a positive integer (booleans are explicitly
  rejected too, since `bool` is a subclass of `int` in Python)

`validate_all()` loads and cross-validates both files together in one call
- useful as a single startup/CI check, matching the same
  "fail loudly on bad configuration" convention already used by
  `symptom_triage.load_rules()`.

## Calculated availability & conflict detection (Phase 6.1, Slice 2)

`backend/availability_service.py` builds on the repository above to turn a
provider's recurring weekly windows into concrete, bookable start times for
one specific date - still **not** wired into `chatbot_logic.py`, `webhook.py`,
or the frontend. This slice only adds a standalone computation module; the
booking conversation flow is completely unchanged.

- **Slots are calculated on demand, not persisted.** `get_available_slots()`
  and `is_slot_available()` recompute their answer from scratch on every
  call, reading `providers.json` / `provider_availability.json` /
  `appointments.json` fresh each time (or using in-memory data a caller
  passes in) - there is no slot table, cache, or generated-slots file
  anywhere.
- **Recurring weekly availability is still the only source configuration.**
  Slot generation reads the same `dayOfWeek`/`startTime`/`endTime`/
  `slotMinutes` windows described above; nothing new is added to that
  schema in this slice.
- **Cancelled appointments free their slot.** An appointment with
  `status: "cancelled"` never blocks availability; a missing `status` is
  treated as `"booked"` (still blocks). An unrecognized status value (e.g.
  `"pending"`) makes the whole calculation fail loudly rather than guess.
- **Legacy appointments without a `providerId` never block a
  provider-specific slot.** Since such a record can't be confidently
  associated with any provider, `availability_service.py` never guesses or
  assigns one - it simply excludes that record from every provider's
  conflict check.
- **Appointment duration is respected for conflict detection**, using
  standard interval-overlap semantics (`candidate_start < existing_end AND
  candidate_end > existing_start`), so a longer existing appointment
  correctly blocks every slot it overlaps, not just its own exact start
  time - while back-to-back appointments (one ending exactly when another
  begins) are allowed, the same way touching availability windows are (see
  `availability_service._check_windows_do_not_overlap`'s docstring). A
  legacy appointment missing `durationMinutes` defaults to the slot size of
  whichever availability window it's being checked against; a *present but
  invalid* `durationMinutes` (a non-positive value, or a non-integer such as
  a string) still fails loudly rather than being silently coerced.
- **Scheduling still uses local clinic time only** - `availability_service.py`
  does no timezone conversion, matching `provider_availability.json`'s own
  scope note above.
- **This slice does not yet modify the booking conversation.** Nothing in
  `chatbot_logic.py` calls `availability_service.py` yet; a user booking an
  appointment today still goes through the exact same flow as before this
  slice existed. Wiring this into the actual booking flow (and introducing
  provider selection) is deliberately a later, separate step.
