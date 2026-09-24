"""Appointment reminder domain logic (Phase 6.2-A foundation).

Concerned only with WHAT reminder should exist and WHEN it is due - never
HOW it is actually delivered. No email/SMS/notification code, and no new
dependency, exists in this module or anywhere else in this slice. See
backend/REMINDER_NOTES.md for the full design, the approved decisions
this module implements, and the future provider-abstraction boundary.

Persistence follows the exact same convention already used by
chatbot_logic.py (appointments.json) and provider_repository.py (its own
two JSON files): a flat JSON array, read fresh on every call, written
back whole. No database, no caching.

Deliberately does NOT import backend.chatbot_logic (that module imports
this one, for its two integration hooks - importing it back here would
create a circular import) - _is_active() below is a small, intentional
duplicate of chatbot_logic._is_active's identical logic, cheap to keep in
sync since it's one line, matching this project's existing tolerance for
small, explicit duplication over a shared-utility import that would
otherwise invert the dependency direction.
"""
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from backend import reminder_config

REMINDERS_FILE = os.path.join(os.path.dirname(__file__), 'reminders.json')

REMINDER_TYPE_24H_BEFORE = "24h_before"

_STATUS_PENDING = "pending"
_STATUS_SENT = "sent"
_STATUS_FAILED = "failed"
_STATUS_CANCELLED = "cancelled"
_KNOWN_STATUSES = (_STATUS_PENDING, _STATUS_SENT, _STATUS_FAILED, _STATUS_CANCELLED)

_REQUIRED_REMINDER_FIELDS = (
    "id", "appointmentId", "type", "sendAt", "status", "createdAt", "sentAt", "failureReason",
)

_TIME_PATTERN = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')


class ReminderDataError(ValueError):
    """Raised when a record in reminders.json is malformed - missing a
    required field, or carrying an unrecognized `status` - rather than
    silently skipping, coercing, or guessing at it. Mirrors
    availability_service.AvailabilityError's identical "unrecognized
    status fails loudly" convention, applied to the reminders store's own
    status field.

    Never raised for an appointment that simply isn't eligible for a
    reminder (see is_eligible_for_reminder) - that is an ordinary "no",
    not a data-integrity problem.
    """


def _is_active(appointment):
    """Duplicate of chatbot_logic._is_active - see this module's own
    docstring for why it's duplicated rather than imported. An
    appointment with no `status` at all (every legacy record) is treated
    as active; only an explicit `status == "cancelled"` is inactive.
    """
    return appointment.get('status') != 'cancelled'


def _validate_reminder(reminder):
    for field in _REQUIRED_REMINDER_FIELDS:
        if field not in reminder:
            raise ReminderDataError(f"reminder record is missing required field {field!r}")
    if reminder["status"] not in _KNOWN_STATUSES:
        raise ReminderDataError(
            f"reminder {reminder.get('id', '?')!r} has an unknown status "
            f"{reminder['status']!r} - must be one of {_KNOWN_STATUSES}"
        )


def _parse_send_at(reminder):
    """Parses a reminder's stored `sendAt` into an aware UTC datetime.

    Raises ReminderDataError (not a bare ValueError) if it isn't a valid
    ISO-8601 timestamp - a stored reminder's sendAt is expected to always
    be well-formed (this module is the only writer), so a failure here
    means the file was corrupted or hand-edited, not an ordinary "no".
    """
    raw = reminder.get("sendAt")
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError) as e:
        raise ReminderDataError(
            f"reminder {reminder.get('id', '?')!r} has an invalid 'sendAt' {raw!r}"
        ) from e
    if parsed.tzinfo is None:
        raise ReminderDataError(
            f"reminder {reminder.get('id', '?')!r} has a naive (non-timezone-aware) 'sendAt' {raw!r}"
        )
    return parsed.astimezone(timezone.utc)


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_reminders_raw(path=None):
    file_path = path or REMINDERS_FILE
    with open(file_path, 'r') as f:
        return json.load(f)


def _save_reminders(reminders, path=None):
    file_path = path or REMINDERS_FILE
    with open(file_path, 'w') as f:
        json.dump(reminders, f, indent=2)


def list_reminders(path=None):
    """Returns every reminder record, raw, in file order.

    A missing file is treated as "no reminders yet" ([]), matching
    chatbot_logic.list_appointments()'s existing convention for a fresh
    checkout. Invalid JSON is a real data-integrity problem there too,
    but is likewise treated as [] here rather than raised, for the exact
    same reason list_appointments() does: the top-level file itself being
    unreadable is a different, unrelated failure mode from an individual
    record being malformed (see ReminderDataError, raised only when a
    specific record's fields are actually inspected, in the functions
    below - not here).
    """
    file_path = path or REMINDERS_FILE
    if not os.path.exists(file_path):
        return []
    try:
        return _read_reminders_raw(path=file_path)
    except json.JSONDecodeError:
        return []


def _parse_appointment_datetime(appointment):
    """Returns a naive datetime representing the appointment's LOCAL
    clinic wall-clock moment (no timezone attached yet - see
    compute_send_at), or None if `date`/`time` are missing or malformed.

    Never raises - a malformed appointment is an ordinary "not eligible"
    outcome (see is_eligible_for_reminder), not a data-integrity problem;
    this is deliberately checked BEFORE any clinic-timezone lookup is
    attempted, so an appointment with a bad date/time never triggers
    reminder_config.ReminderConfigError - the two failure modes are kept
    independent (confirmed by this module's own tests).
    """
    date_str = appointment.get('date')
    time_str = appointment.get('time')
    if not isinstance(date_str, str) or not isinstance(time_str, str):
        return None
    if not _TIME_PATTERN.match(time_str):
        return None
    try:
        date_obj = date.fromisoformat(date_str)
    except ValueError:
        return None
    hour, minute = (int(part) for part in time_str.split(':'))
    return datetime(date_obj.year, date_obj.month, date_obj.day, hour, minute)


def compute_send_at(appointment):
    """Computes the 24h_before send-at moment for `appointment`, as an
    aware UTC datetime - or None if the appointment's date/time are
    missing/malformed (see _parse_appointment_datetime).

    Algorithm (locked design, Phase 6.2-A):
      1. Parse the appointment's local clinic wall-clock moment (naive).
      2. Attach the configured clinic timezone (reminder_config.get_clinic_timezone()).
      3. Convert to UTC.
      4. Subtract a real timedelta(hours=24) - in UTC, never by
         subtracting one calendar day in local wall-clock time, which
         would be wrong across a DST transition (see
         test_reminder_service.py's own DST-boundary test for a concrete
         worked example of the discrepancy this avoids).

    Raises reminder_config.ReminderConfigError if CLINIC_TIMEZONE is
    unset/invalid - only reached when the appointment's own date/time
    parsed successfully; propagates to the caller rather than being
    swallowed here, so the one place this can fail is never hidden.
    """
    local_naive = _parse_appointment_datetime(appointment)
    if local_naive is None:
        return None

    clinic_tz = reminder_config.get_clinic_timezone()
    local_aware = local_naive.replace(tzinfo=clinic_tz)
    appointment_utc = local_aware.astimezone(timezone.utc)
    return appointment_utc - timedelta(hours=24)


def find_pending_reminder(appointment_id, reminder_type, reminders=None, path=None):
    """Returns the single `pending` reminder for (appointment_id,
    reminder_type), or None if there isn't one.

    `reminders`, if given, is used as-is instead of reading `path`/
    REMINDERS_FILE fresh - lets callers that already have the list avoid
    a second read (matching availability_service.py's own `appointments`
    override convention). Validates every candidate's `status` via
    _validate_reminder as it's inspected - raises ReminderDataError on
    the first malformed record encountered, rather than silently
    skipping it.
    """
    if reminders is None:
        reminders = list_reminders(path=path)

    for reminder in reminders:
        if reminder.get("appointmentId") != appointment_id or reminder.get("type") != reminder_type:
            continue
        _validate_reminder(reminder)
        if reminder["status"] == _STATUS_PENDING:
            return reminder
    return None


def is_eligible_for_reminder(appointment, reminder_type=REMINDER_TYPE_24H_BEFORE, now=None, reminders=None, path=None):
    """Pure eligibility predicate for Phase 6.2-A's locked contract:

      - a non-empty, stable appointment `id` (legacy no-id records are
        never eligible - a reminder system needs a stable foreign key)
      - a valid `date` and a valid HH:MM `time`
      - the appointment is active (not cancelled)
      - the computed sendAt is STRICTLY in the future relative to `now`
        (sendAt == now does NOT create a reminder - see compute_send_at
        and this module's own docstring for the creation-vs-due-check
        distinction)
      - no existing `pending` reminder already exists for this exact
        (appointmentId, type) pair

    `providerId` and `durationMinutes` are never consulted - neither is
    required or relevant to reminder eligibility.

    `now`, if given, is used instead of datetime.now(timezone.utc) - lets
    tests exercise exact-boundary behavior deterministically. Raises
    reminder_config.ReminderConfigError only when the appointment's own
    date/time are otherwise valid but the clinic timezone config is not
    (see compute_send_at) - never swallowed here.
    """
    appointment_id = appointment.get('id')
    if not appointment_id:
        return False

    if not _is_active(appointment):
        return False

    send_at = compute_send_at(appointment)
    if send_at is None:
        return False

    current = now if now is not None else datetime.now(timezone.utc)
    if not send_at > current:
        return False

    if find_pending_reminder(appointment_id, reminder_type, reminders=reminders, path=path) is not None:
        return False

    return True


def create_reminder(appointment, reminder_type=REMINDER_TYPE_24H_BEFORE, now=None, path=None):
    """Creates and persists a new `pending` reminder for `appointment`,
    or returns None (a silent no-op) if it isn't eligible right now -
    including the specific case where a `pending` reminder for this exact
    (appointmentId, type) already exists (Phase 6.2-A's locked
    idempotency rule: `sent`/`failed`/`cancelled` reminders are terminal
    history and never block a new creation - only an existing `pending`
    one does).

    Always reads reminders.json (or `path`) fresh immediately before
    checking eligibility, and writes back the full list immediately after
    appending - matching this project's "never trust an earlier snapshot"
    discipline used throughout chatbot_logic.py's own confirm handlers.

    Raises reminder_config.ReminderConfigError if CLINIC_TIMEZONE is
    unset/invalid (see compute_send_at) - callers (chatbot_logic.py's two
    integration hooks) are responsible for deciding how to handle that
    without letting it affect the appointment mutation itself; this
    function does not swallow it.
    """
    reminders = list_reminders(path=path)

    if not is_eligible_for_reminder(appointment, reminder_type, now=now, reminders=reminders, path=path):
        return None

    send_at = compute_send_at(appointment)

    reminder = {
        "id": str(uuid.uuid4()),
        "appointmentId": appointment["id"],
        "type": reminder_type,
        "sendAt": send_at.isoformat(),
        "status": _STATUS_PENDING,
        "createdAt": _utc_now_iso(),
        "sentAt": None,
        "failureReason": None,
    }
    reminders.append(reminder)
    _save_reminders(reminders, path=path)
    return reminder


def cancel_pending_reminder(appointment_id, reminder_type=REMINDER_TYPE_24H_BEFORE, path=None):
    """Transitions every `pending` reminder for (appointment_id,
    reminder_type) to `cancelled` - normally at most one, by the
    idempotency rule above, but this does not assume exactly one (the
    same non-guessing discipline chatbot_logic.py's own
    _pending_transaction_count applies to its own three pending files).
    Never deletes a record - only ever changes its `status`, preserving
    full reminder history exactly like appointment cancellation preserves
    the appointment record itself.

    A `None`/missing `appointment_id` (a legacy appointment with no id)
    safely matches nothing and returns an empty list - no special-casing
    needed, since no stored reminder's `appointmentId` can ever be None.

    Returns the list of reminder ids that were transitioned (possibly
    empty). Never raises reminder_config.ReminderConfigError - cancelling
    never computes a sendAt, so it never needs the clinic timezone.
    """
    reminders = list_reminders(path=path)
    cancelled_ids = []

    for reminder in reminders:
        if reminder.get("appointmentId") != appointment_id or reminder.get("type") != reminder_type:
            continue
        _validate_reminder(reminder)
        if reminder["status"] == _STATUS_PENDING:
            reminder["status"] = _STATUS_CANCELLED
            cancelled_ids.append(reminder["id"])

    if cancelled_ids:
        _save_reminders(reminders, path=path)
    return cancelled_ids


def get_due_reminders(now=None, path=None):
    """Pure callable returning every `pending` reminder whose `sendAt` is
    due: now_utc >= sendAt (inclusive - a reminder scheduled for exactly
    now is due, matching ordinary scheduled-job semantics; contrast with
    is_eligible_for_reminder's strict `>` at CREATION time - see this
    module's own docstring for why the two moments use different
    inequalities).

    Deliberately just a query, not a scheduler: no loop, no polling, no
    background thread, no cron/APScheduler - Phase 6.2-A explicitly
    defers the trigger mechanism (see backend/REMINDER_NOTES.md).
    Raises ReminderDataError on the first malformed record encountered.
    """
    current = now if now is not None else datetime.now(timezone.utc)
    reminders = list_reminders(path=path)

    due = []
    for reminder in reminders:
        _validate_reminder(reminder)
        if reminder["status"] != _STATUS_PENDING:
            continue
        if current >= _parse_send_at(reminder):
            due.append(reminder)
    return due
