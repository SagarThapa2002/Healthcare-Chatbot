"""Deterministic calculated-availability and conflict-detection service.

Phase 6.1, Slice 2. Builds on backend/provider_repository.py (Slice 1):
turns a provider's recurring weekly availability into concrete candidate
start times for one specific calendar date, and excludes any start time
already occupied by an existing, active appointment for that same
provider on that same date.

NOT wired into chatbot_logic.py, webhook.py, or the frontend yet - see
backend/PROVIDER_AVAILABILITY_NOTES.md. This module is pure computation:
appointments.json is only ever opened in 'r' mode (or an in-memory list is
used instead, via the `appointments` parameter), and nothing here writes
to any file. No Flask, frontend, or LLM/assistant import anywhere in this
module.

What this module WILL do:
  - Generate grid-aligned candidate slots from a provider's recurring
    weekly availability windows for one date (get_available_slots).
  - Exclude any candidate slot that overlaps an existing, non-cancelled
    appointment for that same provider on that same date.
  - Validate a single requested (provider, date, time) combination
    against that same computation (is_slot_available).
  - Fail loudly (AvailabilityError) on malformed input (bad date/time
    format, an unknown provider) and on invalid appointment data it
    cannot safely reason about (an unrecognized status, or a present but
    invalid durationMinutes) - never silently normalize or ignore it.

What this module WILL NOT do (deliberately out of scope for this slice):
  - Persist or cache generated slots anywhere. Every call recomputes from
    scratch - see PROVIDER_AVAILABILITY_NOTES.md.
  - Handle holidays, one-off exceptions, or any date-specific override -
    that is still out of scope, per provider_repository.py's own notes.
  - Do any timezone conversion. Every date/time here is local clinic
    time, exactly as written - see PROVIDER_AVAILABILITY_NOTES.md.
  - Touch chatbot_logic.py, webhook.py, response_model.py, or any
    conversation flow. Booking/update/cancel behavior is unchanged.
  - Introduce appointment IDs, database/ORM code, or locking/concurrency
    infrastructure.

Legacy appointment handling (backend/appointments.json's current real
records predate providerId/durationMinutes/status entirely):
  - A missing `status` is treated as `"booked"` (still blocks a slot).
  - A missing `durationMinutes` defaults to the slotMinutes of whichever
    availability window the candidate slot being checked belongs to -
    see _is_occupied()'s docstring for why this is window-relative rather
    than a single global default.
  - A missing `providerId` means the appointment can never be confidently
    associated with any provider, so it is *never* treated as a conflict
    for a provider-specific query - this module never guesses/assigns a
    provider to a legacy record.

Overlapping availability windows (two windows for the same provider on
the same day whose time ranges actually overlap) are rejected with
AvailabilityError - see _check_windows_do_not_overlap()'s docstring for
why touching windows (one ends exactly when another starts) are allowed
instead of also being rejected.
"""
import datetime
import json
import os
import re

from backend import provider_repository

APPOINTMENTS_FILE = os.path.join(os.path.dirname(__file__), 'appointments.json')

_WEEKDAY_NAMES = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)

_DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_TIME_PATTERN = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')

# The only two statuses this slice understands. Anything else is a data
# problem this module cannot safely reason about, so it fails loudly
# rather than guessing - see _is_occupied(). Completed/no-show statuses
# are deliberately not added yet.
_KNOWN_STATUSES = ("booked", "cancelled")


class AvailabilityError(ValueError):
    """Raised for malformed input (an unparseable date/time, or an unknown
    provider id) and for appointment data this module cannot safely
    reason about (an unrecognized status, or an invalid durationMinutes).

    Deliberately fails loudly rather than silently normalizing bad input
    or guessing at bad data - matches provider_repository.ProviderDataError's
    convention, for the same reason.
    """


def _parse_date(date_str):
    if not isinstance(date_str, str) or not _DATE_PATTERN.match(date_str):
        raise AvailabilityError(f"date must be in YYYY-MM-DD format: {date_str!r}")
    try:
        return datetime.date.fromisoformat(date_str)
    except ValueError as e:
        raise AvailabilityError(f"date is not a valid calendar date: {date_str!r}") from e


def _parse_time_to_minutes(value, context):
    if not isinstance(value, str) or not _TIME_PATTERN.match(value):
        raise AvailabilityError(f"{context} is not a valid HH:MM time: {value!r}")
    hours, minutes = value.split(':')
    return int(hours) * 60 + int(minutes)


def _minutes_to_time_str(total_minutes):
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _load_appointments(path=None):
    """Reads appointments.json fresh, read-only.

    A missing file is treated as "no appointments yet" ([]), matching
    chatbot_logic.list_appointments()'s existing convention for a fresh
    checkout with no bookings. Invalid JSON or a non-list top-level value
    is a real data-integrity problem, not an absence, so that still
    raises AvailabilityError rather than silently returning [].
    """
    file_path = path or APPOINTMENTS_FILE

    if not os.path.exists(file_path):
        return []

    with open(file_path, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise AvailabilityError(f"appointments file is not valid JSON: {e}") from e

    if not isinstance(data, list):
        raise AvailabilityError("appointments file must contain a JSON array")

    return data


def _check_windows_do_not_overlap(windows, provider_id, weekday):
    """Rejects two availability windows for the same provider/weekday whose
    time ranges genuinely overlap, using the exact same strict interval
    overlap test as appointment conflict detection (start < other_end AND
    end > other_start). Windows that merely touch (one's endTime equals
    another's startTime) do NOT satisfy that test, so they are allowed -
    deliberately mirroring the "back-to-back appointments are allowed"
    rule for appointments, and because a touching pair never produces a
    duplicate slot (each grid is generated independently, starting from
    its own window's startTime).
    """
    parsed = [
        (_parse_time_to_minutes(w["startTime"], "window startTime"),
         _parse_time_to_minutes(w["endTime"], "window endTime"), w)
        for w in windows
    ]
    for i in range(len(parsed)):
        start_a, end_a, window_a = parsed[i]
        for start_b, end_b, window_b in parsed[i + 1:]:
            if start_a < end_b and end_a > start_b:
                raise AvailabilityError(
                    f"provider {provider_id!r} has overlapping availability windows on "
                    f"{weekday!r}: {window_a['startTime']}-{window_a['endTime']} and "
                    f"{window_b['startTime']}-{window_b['endTime']}"
                )


def _validate_duration(appointment, default_duration_minutes):
    if "durationMinutes" not in appointment:
        return default_duration_minutes

    duration = appointment["durationMinutes"]
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        raise AvailabilityError(
            f"appointment for provider {appointment.get('providerId')!r} on "
            f"{appointment.get('date')!r} at {appointment.get('time')!r} has an invalid "
            f"'durationMinutes' {duration!r} - must be a positive integer"
        )
    return duration


def _is_occupied(candidate_start, candidate_end, relevant_appointments, default_duration_minutes):
    """Checks one candidate [candidate_start, candidate_end) interval (in
    minutes since midnight) against appointments already filtered down to
    "same provider, same date" by the caller.

    `default_duration_minutes` is the slotMinutes of the specific
    availability window the candidate slot came from - a legacy
    appointment missing durationMinutes is assumed to last exactly that
    long. This is window-relative rather than a single global default so
    that a provider with two same-day windows of different slot sizes
    (not present in today's synthetic data, but not disallowed either)
    still gets a locally sensible default for each window it's compared
    against, rather than an arbitrary cross-window choice.
    """
    for appointment in relevant_appointments:
        status = appointment.get("status", "booked")
        if status not in _KNOWN_STATUSES:
            raise AvailabilityError(
                f"appointment for provider {appointment.get('providerId')!r} on "
                f"{appointment.get('date')!r} has an unknown status {status!r} - "
                f"must be one of {_KNOWN_STATUSES}"
            )
        if status == "cancelled":
            continue

        existing_start = _parse_time_to_minutes(
            appointment.get("time"),
            f"existing appointment for provider {appointment.get('providerId')!r} 'time'",
        )
        duration = _validate_duration(appointment, default_duration_minutes)
        existing_end = existing_start + duration

        if candidate_start < existing_end and candidate_end > existing_start:
            return True

    return False


def _slots_for_window(window, relevant_appointments):
    slot_minutes = window["slotMinutes"]
    window_start = _parse_time_to_minutes(window["startTime"], "window startTime")
    window_end = _parse_time_to_minutes(window["endTime"], "window endTime")

    slots = []
    current = window_start
    while current + slot_minutes <= window_end:
        if not _is_occupied(current, current + slot_minutes, relevant_appointments, slot_minutes):
            slots.append(_minutes_to_time_str(current))
        current += slot_minutes
    return slots


def get_available_slots(provider_id, date, appointments=None, providers=None, availability=None):
    """Returns every available start time (e.g. ["09:00", "09:30", ...])
    for `provider_id` on `date` (a "YYYY-MM-DD" string), derived from that
    provider's recurring weekly availability for that date's weekday.

    A slot must fit entirely within its availability window - the window's
    own endTime is never itself returned as a start time. Multiple windows
    on the same weekday (e.g. a morning and an afternoon window) each
    generate their own independent slots; nothing is generated in a gap
    between windows. Slots are computed fresh on every call, never
    persisted.

    Raises AvailabilityError for a malformed `date`, an unknown
    `provider_id`, or availability windows for that provider/weekday that
    genuinely overlap. Returns [] (not an error) when the provider simply
    has no availability configured for that weekday - that is a normal,
    legitimate outcome, not a data problem.

    `appointments`/`providers`/`availability`, if given, are used as-is
    instead of reading backend/appointments.json /
    backend/provider_repository.py's own files - lets tests exercise this
    function entirely in-memory. When omitted, each is loaded fresh via
    provider_repository / this module's own _load_appointments(), matching
    the "always read current data, never cache" convention already used
    throughout this codebase.
    """
    date_obj = _parse_date(date)
    weekday = _WEEKDAY_NAMES[date_obj.weekday()]

    if providers is None:
        providers = provider_repository.load_providers()
    provider = provider_repository.find_provider(provider_id, providers=providers)
    if provider is None:
        raise AvailabilityError(f"unknown provider: {provider_id!r}")

    if availability is None:
        availability = provider_repository.load_availability(providers=providers)
    provider_windows = provider_repository.get_provider_availability(provider_id, availability=availability)
    day_windows = [w for w in provider_windows if w["dayOfWeek"] == weekday]

    if not day_windows:
        return []

    _check_windows_do_not_overlap(day_windows, provider_id, weekday)

    if appointments is None:
        appointments = _load_appointments()
    relevant_appointments = [
        a for a in appointments
        if a.get("providerId") == provider_id and a.get("date") == date
    ]

    slots = []
    for window in day_windows:
        slots.extend(_slots_for_window(window, relevant_appointments))
    return slots


def is_slot_available(provider_id, date, time, appointments=None, providers=None, availability=None):
    """Returns True only if `time` is one of get_available_slots()'s
    candidate start times for `provider_id` on `date` - i.e. it falls on
    that provider's slot grid for that weekday, fits entirely inside an
    availability window, and isn't already occupied by an active,
    same-provider appointment.

    A well-formed `time` that doesn't land on the slot grid at all (e.g.
    "09:17" when slots start every 30 minutes from "09:00") is treated as
    simply unavailable (False), not a format error - it is not one of the
    slots this provider actually offers, but it is not malformed input
    either.

    Raises AvailabilityError for a malformed `date` or `time`, or an
    unknown `provider_id` - these are input problems, not "unavailable"
    outcomes, so they must not be confused with a plain False. Returns
    False (never raises) when the provider has no availability at all
    that weekday, the requested time doesn't fit within any window, or it
    conflicts with an existing appointment.
    """
    _parse_time_to_minutes(time, "requested 'time'")
    available = get_available_slots(
        provider_id, date, appointments=appointments, providers=providers, availability=availability
    )
    return time in available
