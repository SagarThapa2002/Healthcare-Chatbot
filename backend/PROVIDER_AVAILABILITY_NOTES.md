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
