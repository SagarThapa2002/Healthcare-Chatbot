"""Application/service logic for the healthcare chatbot.

This is the same per-intent logic that used to live inline in webhook.py,
relocated so webhook.py can stay a thin HTTP adapter. Behavior is
preserved exactly, including a couple of pre-existing inconsistencies in
how corrupt appointments.json is handled between branches (see
_handle_update_appointment / _handle_cancel_appointment vs _handle_yes_intent
and _handle_view_appointments below) - those are carried over unchanged,
not "fixed", since fixing them wasn't asked for in this phase.

Phase 6.1, Slice 3, Step 1 added _format_provider_list() and
_format_slot_list() as standalone formatting helpers. Step 2 (this
revision) wires provider selection and calculated availability into
_handle_book_appointment itself: the booking sequence is now
NAME -> PROVIDER -> DATE -> SLOT -> CONFIRM. _handle_yes_intent is
UNCHANGED in this step - it still just persists whatever pending dict it
finds, which now happens to include "providerId" - the final
re-validate-before-write safety check is a later step, not this one. See
backend/PROVIDER_AVAILABILITY_NOTES.md.
"""
import json
import logging
import os
import uuid

from backend import assistant_service
from backend import availability_service
from backend import llm_config
from backend import provider_repository
from backend import response_model

logger = logging.getLogger(__name__)

APPOINTMENTS_FILE = os.path.join(os.path.dirname(__file__), 'appointments.json')
PENDING_FILE = os.path.join(os.path.dirname(__file__), 'pending_appointments.json')
# Deliberately a separate file from PENDING_FILE above - a pending
# cancellation and a pending booking are unrelated flows and must never
# share or collide over the same global slot. Same known limitation as
# PENDING_FILE: a single global file, no per-session scoping, no file
# locking - not solved here, only documented (see
# backend/PROVIDER_AVAILABILITY_NOTES.md).
PENDING_CANCELLATION_FILE = os.path.join(os.path.dirname(__file__), 'pending_cancellation.json')
# Phase 6.1 Slice B: a pending update is a third, independent global slot -
# same limitation as the two above (single global file, no per-session
# scoping, no file locking). Booking, cancellation, and update pending
# state are treated as MUTUALLY EXCLUSIVE (see _handle_update_appointment's
# own guard and _pending_transaction_count() below), rather than given an
# arbitrary priority order the way a two-way tie would otherwise need.
PENDING_UPDATE_FILE = os.path.join(os.path.dirname(__file__), 'pending_update.json')


def _read_appointments_raw():
    with open(APPOINTMENTS_FILE, 'r') as f:
        return json.load(f)


def _save_appointments(appointments):
    with open(APPOINTMENTS_FILE, 'w') as f:
        json.dump(appointments, f, indent=2)


def list_appointments():
    if not os.path.exists(APPOINTMENTS_FILE):
        return []
    try:
        return _read_appointments_raw()
    except json.JSONDecodeError:
        return []


def handle_webhook_request(payload, request_id=None):
    query_result = payload.get('queryResult', {})
    intent = query_result.get('intent', {}).get('displayName', '')
    parameters = query_result.get('parameters', {})

    logger.info("dispatching request_id=%s intent=%s", request_id, intent)

    # Only Book Appointment / YesIntent ever set this - every other intent
    # leaves it None, so response_model.success_response() omits
    # `bookingStage` from `context` for them entirely (see its docstring).
    booking_stage = None
    # Same idea, for the cancel-by-ID flow - see success_response's
    # docstring. Only Cancel Appointment / a YesIntent-or-NoIntent that
    # resolves to a pending cancellation (see below) ever set this.
    cancellation_stage = None
    # Same idea again, for Phase 6.1 Slice B's update-by-ID flow. Only
    # Update Appointment / a YesIntent-or-NoIntent that resolves to a
    # pending update (see below) ever set this.
    update_stage = None

    if intent == "Symptom Check":
        messages = _handle_symptom_check(parameters)
    elif intent == "Book Appointment":
        messages, booking_stage = _handle_book_appointment(parameters)
    elif intent == "YesIntent":
        # Booking, cancellation, and update pending state are mutually
        # exclusive (see PENDING_UPDATE_FILE's own comment and
        # _handle_update_appointment's own guard) - normally at most one
        # of the three pending files exists at a time, and this simply
        # routes to whichever one it is. If more than one somehow exists
        # anyway (a leaked/partial state from an earlier bug, not a
        # reachable outcome of normal use), this deliberately does not
        # guess which one the user meant - it fails closed with a generic
        # message instead. _handle_yes_intent's / _handle_cancel_confirm_yes's
        # own bodies are untouched either way - this only decides which
        # handler a bare "yes" reaches.
        if _pending_transaction_count() > 1:
            messages = _handle_ambiguous_pending_transactions()
        elif os.path.exists(PENDING_UPDATE_FILE):
            messages, update_stage = _handle_update_confirm_yes()
        elif os.path.exists(PENDING_CANCELLATION_FILE):
            messages, cancellation_stage = _handle_cancel_confirm_yes()
        else:
            messages, booking_stage = _handle_yes_intent()
    elif intent == "NoIntent":
        if _pending_transaction_count() > 1:
            messages = _handle_ambiguous_pending_transactions()
        elif os.path.exists(PENDING_UPDATE_FILE):
            messages, update_stage = _handle_update_confirm_no()
        elif os.path.exists(PENDING_CANCELLATION_FILE):
            messages, cancellation_stage = _handle_cancel_confirm_no()
        else:
            messages = _handle_no_intent()
    elif intent == "Update Appointment":
        messages, update_stage = _handle_update_appointment(parameters)
    elif intent == "Cancel Appointment":
        messages, cancellation_stage = _handle_cancel_appointment(parameters)
    elif intent == "View Appointments":
        messages = _handle_view_appointments()
    elif intent == "General FAQ":
        messages = _handle_general_faq(parameters, request_id=request_id)
    else:
        messages = [response_model.text_message(
            "Sorry, I didn't understand that. Could you rephrase or ask something else?"
        )]

    return response_model.success_response(
        messages, intent=intent, request_id=request_id,
        booking_stage=booking_stage, cancellation_stage=cancellation_stage,
        update_stage=update_stage,
    )


def _pending_transaction_count():
    """Counts how many of the three mutually-exclusive global pending
    transaction files currently exist (booking, cancellation, update).
    Normally 0 or 1 - see PENDING_UPDATE_FILE's own comment and
    _handle_update_appointment's guard, which refuses to create a pending
    update while a pending booking or cancellation already exists. Used by
    handle_webhook_request to fail closed on a bare "yes"/"no" if more
    than one somehow exists at once, rather than guessing which the user
    meant.
    """
    return sum([
        os.path.exists(PENDING_FILE),
        os.path.exists(PENDING_CANCELLATION_FILE),
        os.path.exists(PENDING_UPDATE_FILE),
    ])


def _handle_ambiguous_pending_transactions():
    logger.warning(
        "multiple pending transactional files exist at once - failing closed on YesIntent/NoIntent"
    )
    text = (
        "Something went wrong - more than one action is waiting for confirmation. "
        "Please try again in a moment."
    )
    return [response_model.text_message(text)]


def _handle_symptom_check(parameters):
    symptom = parameters.get('symptom')
    if symptom:
        text = f"Thanks for sharing. Since you're experiencing {symptom}, I recommend keeping an eye on it. If it worsens, please consider visiting a healthcare provider."
    else:
        text = "Could you please tell me your symptom so I can assist you better?"
    return [response_model.text_message(text)]


def _format_provider_list():
    """Deterministic, human-readable numbered list of every known provider.

    Not called from _handle_book_appointment or anywhere else yet - see
    the module docstring's Step 1 scope note. Reads provider data
    exclusively through provider_repository.list_providers() (never
    providers.json directly), so this module never duplicates that
    module's file I/O or validation, and never mutates what it returns.

    Returns a single, ready-to-display string such as:

        1. Dr. Patel - General Practice (Main Clinic)
        2. Dr. Nguyen - Pediatrics (Main Clinic)

    in the same order provider_repository.list_providers() returns them
    (file order) - deterministic given the same providers.json, and never
    re-sorted here, so a future caller can safely interpret a numeric
    reply like "2" as the second entry without this function and a later
    re-read ever disagreeing on order.
    """
    providers = provider_repository.list_providers()
    if not providers:
        return "No providers are currently configured."

    lines = [
        f"{index}. {provider['name']} - {provider['specialty']} ({provider['location']})"
        for index, provider in enumerate(providers, start=1)
    ]
    return "\n".join(lines)


def _format_slot_list(provider_id, date):
    """Deterministic, human-readable numbered list of a provider's
    available start times on one date.

    Not called from _handle_book_appointment or anywhere else yet - see
    the module docstring's Step 1 scope note. Delegates entirely to
    availability_service.get_available_slots(): this function contains no
    slot-generation or conflict-detection logic of its own, and never
    reads appointments.json or provider_availability.json directly or
    mutates either.

    Returns a single, ready-to-display string such as:

        1. 09:00
        2. 09:30

    using the HH:MM local-clinic-time values exactly as
    get_available_slots() returns them - no reformatting or timezone
    conversion. A "no slots" message is returned (not an exception) for
    an empty list - availability_service.py's own notes describe two
    different reasons an empty list can occur (no availability configured
    that weekday, vs. a fully booked day); this formatter deliberately
    does not distinguish between them, since that distinction belongs to
    the later booking-flow integration step, not to formatting.

    Raises availability_service.AvailabilityError exactly when
    get_available_slots() would (e.g. an unknown provider_id or a
    malformed date) - not caught or reinterpreted here. Handling that is
    the responsibility of whatever calls this once it's wired into the
    booking flow.
    """
    slots = availability_service.get_available_slots(provider_id, date)
    if not slots:
        return "No available slots for that date."

    lines = [f"{index}. {slot}" for index, slot in enumerate(slots, start=1)]
    return "\n".join(lines)


_WEEKDAY_ORDER = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)


def _resolve_provider_choice(choice):
    """Resolves a raw, user-typed provider selection to a canonical
    provider id, or None if it doesn't unambiguously match anything.

    Accepts, in this order: a 1-based number matching
    _format_provider_list()'s displayed order; an exact provider id
    (case-insensitive); an exact provider name (case-insensitive). Never
    guesses - an unmatched or ambiguous choice returns None so the caller
    re-prompts instead of silently picking a provider (see
    _handle_book_appointment below). Reads through
    provider_repository.list_providers() only, never providers.json
    directly, and never mutates what it reads.
    """
    if not choice or not isinstance(choice, str):
        return None

    normalized = choice.strip()
    if not normalized:
        return None

    providers = provider_repository.list_providers()

    if normalized.isdigit():
        index = int(normalized)
        if 1 <= index <= len(providers):
            return providers[index - 1]["id"]
        return None

    lowered = normalized.lower()
    for provider in providers:
        if provider["id"].lower() == lowered or provider["name"].lower() == lowered:
            return provider["id"]

    return None


def _configured_weekdays(provider_id):
    """Returns the distinct weekdays `provider_id` has ANY configured
    availability window on, Monday-first - used only to compose a "they're
    usually available on..." message when a requested date has none.
    Reads through provider_repository.get_provider_availability() only,
    never provider_availability.json directly, and never mutates it.
    """
    windows = provider_repository.get_provider_availability(provider_id)
    configured = {window["dayOfWeek"] for window in windows}
    return [day for day in _WEEKDAY_ORDER if day in configured]


# _check_date_availability()'s three non-error outcomes.
_DATE_NO_WEEKDAY_AVAILABILITY = "no_weekday_availability"
_DATE_FULLY_BOOKED = "fully_booked"
_DATE_HAS_SLOTS = "has_slots"


def _check_date_availability(provider_id, date):
    """Determines whether provider_id has any bookable slot on `date`, and
    if not, which of two distinct reasons applies - without duplicating
    availability_service.py's own weekday/slot-generation arithmetic. It
    only ever calls the existing public get_available_slots(), once with
    an empty `appointments` override and once for real:

      - the override call answers "does this weekday have ANY configured
        availability at all", independent of existing bookings;
      - if so, the real call distinguishes "has open slots" from "every
        slot is already taken" (fully booked).

    Returns a (status, slots) tuple:
      (_DATE_NO_WEEKDAY_AVAILABILITY, [])         - no windows that weekday at all
      (_DATE_FULLY_BOOKED, [])                    - windows exist, but every slot is taken
      (_DATE_HAS_SLOTS, [<slot>, ...])             - real, currently bookable slots

    Raises availability_service.AvailabilityError exactly when
    get_available_slots() would (e.g. a malformed date) - not caught or
    reinterpreted here; see _handle_book_appointment's own handling of
    that, which follows the same "safe fallback message, never a raw
    exception" convention as assistant_service.answer().
    """
    raw_slots = availability_service.get_available_slots(provider_id, date, appointments=[])
    if not raw_slots:
        return _DATE_NO_WEEKDAY_AVAILABILITY, []

    real_slots = availability_service.get_available_slots(provider_id, date)
    if not real_slots:
        return _DATE_FULLY_BOOKED, []

    return _DATE_HAS_SLOTS, real_slots


def _resolve_slot_choice(choice, provider_id, date):
    """Resolves a raw, user-typed slot selection to a validated HH:MM
    start time, or None if it isn't currently available.

    Accepts an exact HH:MM value or a 1-based number matching
    _format_slot_list()'s displayed order for this exact provider_id/date.
    Either way, availability is re-checked fresh here via
    availability_service (is_slot_available() for an exact value,
    get_available_slots() for a numeric index) rather than trusting the
    list shown earlier or the mere shape of the input - a slot taken by
    someone else between the prompt and this reply is correctly rejected.
    Never mutates appointment or availability data (both are read-only
    lookups).

    By this point provider_id/date have already been validated by
    _handle_book_appointment, so an AvailabilityError here can only be
    about `choice` itself (e.g. is_slot_available() rejects a value that
    isn't a well-formed HH:MM string) or an appointment-data problem
    availability_service refuses to guess about. Either way, from the
    slot-selection stage's point of view that's simply "not a valid
    choice" - this function catches it, logs the exception type only (per
    this project's logging conventions - never the raw choice text or
    exception message), and returns None so the caller re-prompts with
    the current list exactly as it would for an ordinary unmatched value,
    rather than surfacing a different, exception-shaped outcome.
    """
    if not choice or not isinstance(choice, str):
        return None

    normalized = choice.strip()
    if not normalized:
        return None

    try:
        if normalized.isdigit():
            slots = availability_service.get_available_slots(provider_id, date)
            index = int(normalized)
            if 1 <= index <= len(slots):
                return slots[index - 1]
            return None

        if availability_service.is_slot_available(provider_id, date, normalized):
            return normalized
        return None
    except availability_service.AvailabilityError as e:
        logger.warning(
            "booking slot choice could not be validated provider_id=%s exception_type=%s",
            provider_id, type(e).__name__,
        )
        return None


def _handle_book_appointment(parameters):
    """NAME -> PROVIDER -> DATE -> SLOT -> CONFIRM.

    Phase 6.1, Slice 3, Step 2. Exactly like the original name/date/time
    chain this replaces, this function is stateless per-request: it only
    ever looks at whichever fields are present in `parameters` THIS call
    (the caller - eventually the frontend's booking state, not yet
    changed in this step - is responsible for resending the accumulated
    fields on every turn). `providerId` and `time` both carry RAW,
    unvalidated user text until resolved below - once resolved, the
    canonical values are what get written to pending_appointments.json,
    so a caller that simply echoes back what it was given keeps working
    correctly turn over turn.

    Every availability_service call in this function is wrapped so an
    AvailabilityError (a malformed date slipping through, or invalid
    appointment data availability_service itself refuses to guess about)
    becomes a safe, deterministic fallback message - never a raw
    exception surfaced to the caller - matching the same convention
    assistant_service.answer() already uses for provider failures.

    Returns (messages, booking_stage) - Phase 6.1, Slice 3, Step 4
    (revised): `booking_stage` is one of "name", "provider", "date",
    "slot", "confirm", reported alongside the existing text at every
    return point, so a caller can tell "advanced" from "rejected, still
    on this same stage" structurally (see response_model.success_response's
    docstring) without inspecting `text` or duplicating the validation
    decision made right here. This function still owns 100% of that
    validation - the return value only ever *labels* a decision already
    made above it, never adds a new one.
    """
    parameters = parameters or {}
    name = parameters.get('name')
    provider_choice = parameters.get('providerId')
    date = parameters.get('date')
    slot_choice = parameters.get('time')

    if not name:
        text = "Sure, may I have your name for the appointment?"
        return [response_model.text_message(text)], "name"

    if not provider_choice:
        text = f"Thanks {name}. Which provider would you like to see?\n{_format_provider_list()}"
        return [response_model.text_message(text)], "provider"

    provider_id = _resolve_provider_choice(provider_choice)
    if provider_id is None:
        text = (
            "Sorry, I didn't recognize that provider. Please choose one from the list:\n"
            f"{_format_provider_list()}"
        )
        return [response_model.text_message(text)], "provider"

    if not date:
        provider = provider_repository.find_provider(provider_id)
        provider_name = provider["name"] if provider else provider_id
        text = f"What date would you like to see {provider_name}? (YYYY-MM-DD)"
        return [response_model.text_message(text)], "date"

    try:
        status, _ = _check_date_availability(provider_id, date)
    except availability_service.AvailabilityError as e:
        logger.warning(
            "booking date availability check failed provider_id=%s exception_type=%s",
            provider_id, type(e).__name__,
        )
        text = "I couldn't check availability for that date. Could you give me a date in YYYY-MM-DD format?"
        return [response_model.text_message(text)], "date"

    provider = provider_repository.find_provider(provider_id)
    provider_name = provider["name"] if provider else provider_id

    if status == _DATE_NO_WEEKDAY_AVAILABILITY:
        weekdays = _configured_weekdays(provider_id)
        if weekdays:
            text = (
                f"{provider_name} isn't available that day. They're typically available on: "
                f"{', '.join(weekdays)}. What other date would you like?"
            )
        else:
            text = (
                f"{provider_name} doesn't have any configured availability right now. "
                "Could you try a different provider or date?"
            )
        return [response_model.text_message(text)], "date"

    if status == _DATE_FULLY_BOOKED:
        text = f"{provider_name} is fully booked on {date}. Could you try a different date?"
        return [response_model.text_message(text)], "date"

    # status == _DATE_HAS_SLOTS
    if not slot_choice:
        text = f"Here are the available times on {date}:\n{_format_slot_list(provider_id, date)}"
        return [response_model.text_message(text)], "slot"

    # _resolve_slot_choice never raises - any AvailabilityError it hits
    # (a malformed choice, or a data problem) is already turned into a
    # plain None (see its own docstring), so an invalid/unavailable
    # choice and an internal validation problem both correctly land here.
    resolved_time = _resolve_slot_choice(slot_choice, provider_id, date)

    if resolved_time is None:
        text = (
            "Sorry, that time isn't available anymore. Here are the current options:\n"
            f"{_format_slot_list(provider_id, date)}"
        )
        return [response_model.text_message(text)], "slot"

    pending = {
        "name": name,
        "providerId": provider_id,
        "date": date,
        "time": resolved_time,
    }
    with open(PENDING_FILE, 'w') as f:
        json.dump(pending, f, indent=2)
    text = (
        f"Please confirm — book appointment with {provider_name} for {name} on "
        f"{date} at {resolved_time}? (yes or no)"
    )

    return [response_model.text_message(text)], "confirm"


def _handle_yes_intent():
    """Phase 6.1, Slice 3, Step 3 added a final availability re-check
    immediately before the persist step below, closing the race where the
    slot shown/validated during booking (Step 2) gets taken by a
    different booking before this confirmation arrives. Never trusts the
    earlier check - always re-verifies the exact providerId/date/time
    fresh, via the same availability_service.is_slot_available() used
    during booking, and never silently guesses a provider for a pending
    record that's missing one (see the guard below) - that record simply
    cannot be confirmed by this flow.

    On any failure (missing fields, a data problem availability_service
    itself refuses to guess about, or a genuinely-taken slot), the
    pending record is deliberately left in place - only a successful
    confirmation (or an explicit "no") clears it - and no appointment is
    appended.

    Next Phase 6.1 slice: a stable `id` (str(uuid.uuid4()), matching
    response_model._new_request_id()'s existing convention) is generated
    here and added to the appointment dict immediately before it is
    persisted - the only point in the codebase where a new appointment is
    actually created. This is additive only: existing legacy records in
    appointments.json have no `id` and are not migrated or backfilled;
    _handle_update_appointment/_handle_cancel_appointment/
    _handle_view_appointments are unchanged and still operate by name
    only - wiring them to use `id` is a deliberate, separate, later step.

    Returns (messages, booking_stage) - Phase 6.1, Slice 3, Step 4
    (revised): reports "booked" only for a genuine successful
    confirmation. Every failure path reports None (no booking_stage) -
    the frontend already unconditionally resets its local booking state
    after any "yes"/"no" reply regardless of outcome, so none of these
    failure cases need a stage label for that existing behavior to work;
    None simply omits `bookingStage` from the response (see
    response_model.success_response's docstring).
    """
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, 'r') as f:
            appointment = json.load(f)

        provider_id = appointment.get('providerId')
        date = appointment.get('date')
        time = appointment.get('time')

        if not provider_id or not date or not time:
            logger.warning("booking confirmation rejected - pending record is missing required fields")
            text = (
                "Sorry, I couldn't confirm that appointment because some details are missing. "
                "Please choose a provider, date, and time again."
            )
            return [response_model.text_message(text)], None

        try:
            slot_still_available = availability_service.is_slot_available(provider_id, date, time)
        except availability_service.AvailabilityError as e:
            logger.warning(
                "booking confirmation availability re-check failed provider_id=%s exception_type=%s",
                provider_id, type(e).__name__,
            )
            text = "Sorry, I couldn't confirm that appointment right now. Please choose another time or date."
            return [response_model.text_message(text)], None

        if not slot_still_available:
            text = (
                "Sorry, that time is no longer available - it looks like it was just booked. "
                "Please choose another time or date."
            )
            return [response_model.text_message(text)], None

        appointments = []
        if os.path.exists(APPOINTMENTS_FILE):
            try:
                appointments = _read_appointments_raw()
            except json.JSONDecodeError:
                appointments = []

        appointment['id'] = str(uuid.uuid4())
        appointments.append(appointment)
        _save_appointments(appointments)
        os.remove(PENDING_FILE)

        text = f"Your appointment for {appointment['name']} on {appointment['date']} at {appointment['time']} has been booked."
        return [response_model.booking_confirmation_message(text, appointment)], "booked"

    text = "There is no appointment pending confirmation."
    return [response_model.text_message(text)], None


def _handle_no_intent():
    if os.path.exists(PENDING_FILE):
        os.remove(PENDING_FILE)
        text = "No problem! Appointment booking has been canceled. Let me know if you'd like to try again."
    else:
        text = "There is no pending appointment to cancel."
    return [response_model.text_message(text)]


_UPDATE_STAGE_IDENTIFIER = "identifier"
_UPDATE_STAGE_FIELDS = "fields"
_UPDATE_STAGE_CONFIRM = "confirm"
_UPDATE_STAGE_UPDATED = "updated"


def _matches_pending_update(appointment, pending):
    """Re-identifies the exact appointment a pending update refers to,
    without ever falling back to "first matching name" - mirrors
    _matches_pending_cancellation's own reasoning exactly. Prefers the
    stable `id` when the pending record has one; for a legacy no-id
    record, requires an exact match on name AND originalDate AND
    originalTime together (all three captured verbatim from the original
    record at selection time, not typed by the user, and named
    "original*" here specifically so they're never confused with the
    pending record's own newDate/newTime - the values being applied).
    """
    if 'id' in pending:
        return appointment.get('id') == pending['id']
    return (
        appointment.get('name') == pending.get('name')
        and appointment.get('date') == pending.get('originalDate')
        and appointment.get('time') == pending.get('originalTime')
    )


def _check_update_availability(appointment, appointments, check_date, check_time):
    """Validates a proposed (possibly partial) date/time change for
    `appointment` against availability_service, with `appointment` itself
    excluded from its own conflict check (by identity, via `is`) - without
    this, an update that doesn't actually change the slot would always
    "conflict" with itself. A legacy appointment with no `providerId`
    can't be meaningfully checked against any provider's schedule (see
    availability_service.py's own documented convention: a missing
    providerId is never treated as a conflict for a provider-specific
    query) - this function skips validation entirely for that case and
    always reports "ok", matching that convention.

    Returns (ok, error_text) - `error_text` is a ready-to-show, safe
    message and is only non-None when `ok` is False. Never raises: an
    AvailabilityError from the underlying check is caught and turned into
    an "ok=False" outcome with a safe fallback message, matching this
    module's existing convention for date/slot validation elsewhere
    (_handle_book_appointment, _handle_yes_intent).
    """
    provider_id = appointment.get('providerId')
    if not provider_id:
        return True, None

    try:
        other_appointments = [a for a in appointments if a is not appointment]
        slot_ok = availability_service.is_slot_available(
            provider_id, check_date, check_time, appointments=other_appointments,
        )
    except availability_service.AvailabilityError as e:
        logger.warning(
            "update availability check failed provider_id=%s exception_type=%s",
            provider_id, type(e).__name__,
        )
        return False, (
            "I couldn't check availability for that date/time. Could you give a date in "
            "YYYY-MM-DD format and a time in HH:MM format?"
        )

    if not slot_ok:
        return False, (
            f"Sorry, {check_date} at {check_time} isn't available for that provider. "
            "Could you choose a different date or time?"
        )

    return True, None


def _handle_update_appointment(parameters):
    """IDENTIFIER -> FIELDS -> CONFIRM -> UPDATED.

    Phase 6.1 Slice B. Replaces the previous immediate-mutation,
    name-only, unconfirmed update with a safe, confirmed, ID-preferring
    flow. Returns (messages, update_stage) - see
    response_model.success_response's docstring for the stage vocabulary.

    Lookup rules are identical in structure to _handle_cancel_appointment's
    (see its own docstring): an explicit `id` must exactly match an ACTIVE
    appointment's `id` (no fallback to `name`); otherwise `name` is
    matched case-insensitively against ACTIVE appointments only - zero
    matches is "not found", exactly one proceeds, more than one triggers a
    deterministic disambiguation (never a guess) that asks for the id. A
    legacy no-id record remains updateable alone by unique name; an
    ambiguous group containing one explains the limitation and changes
    nothing, exactly like cancellation.

    Only `date`/`time` are ever written to the eventual appointment record
    - `id`, `name`, `providerId`, `durationMinutes`, `status` are always
    preserved untouched (see _handle_update_confirm_yes below, the only
    place anything is actually written).

    Booking, cancellation, and update pending state are mutually
    exclusive (see PENDING_UPDATE_FILE's own comment): if a pending
    booking or cancellation already exists, no pending update is ever
    created here - the caller is told to resolve the existing one first,
    deterministically, rather than silently overwriting or racing it.
    """
    parameters = parameters or {}

    if os.path.exists(PENDING_FILE) or os.path.exists(PENDING_CANCELLATION_FILE):
        text = (
            "You already have another appointment action waiting for confirmation. "
            "Please reply \"yes\" or \"no\" to finish that first, then try updating "
            "an appointment."
        )
        return [response_model.text_message(text)], None

    appointment_id = parameters.get('id')
    name = parameters.get('name')
    new_date = parameters.get('date')
    new_time = parameters.get('time')

    if not appointment_id and not name:
        text = "Sure - what's the ID or name on the appointment you'd like to update?"
        return [response_model.text_message(text)], _UPDATE_STAGE_IDENTIFIER

    if not os.path.exists(APPOINTMENTS_FILE):
        return [response_model.text_message("There are no appointments to update yet.")], None

    appointments = _read_appointments_raw()

    if appointment_id:
        selected = None
        for appointment in appointments:
            if appointment.get('id') == appointment_id:
                selected = appointment
                break
        if selected is None or not _is_active(selected):
            text = "I couldn't find an active appointment with that ID. Please check the ID and try again."
            return [response_model.text_message(text)], _UPDATE_STAGE_IDENTIFIER
    else:
        candidates = [
            a for a in appointments
            if _is_active(a) and a.get('name', '').lower() == name.lower()
        ]
        if not candidates:
            text = f"I couldn't find an appointment for {name} to update."
            return [response_model.text_message(text)], None

        if len(candidates) > 1:
            lines = [_describe_candidate(a) for a in candidates]
            if any(not a.get('id') for a in candidates):
                text = (
                    f"I found multiple appointments for {name}, and at least one of them "
                    "doesn't have a reference ID yet, so I can't safely tell them apart. "
                    "Here they are - none have been changed:\n" + "\n".join(lines)
                )
                return [response_model.text_message(text)], _UPDATE_STAGE_IDENTIFIER

            text = (
                f"I found multiple appointments for {name}. Please tell me the appointment ID "
                "of the one you'd like to update:\n" + "\n".join(lines)
            )
            suggestions = [
                {"id": a["id"], "label": f"{a['date']} at {a['time']}", "value": a["id"]}
                for a in candidates
            ]
            return [response_model.text_message(text, suggestions=suggestions)], _UPDATE_STAGE_IDENTIFIER

        selected = candidates[0]

    if not new_date and not new_time:
        text = (
            f"Got it - the appointment for {selected['name']} on {selected['date']} at "
            f"{selected['time']}. What would you like to change - a new date, a new time, "
            "or both?"
        )
        return [response_model.text_message(text)], _UPDATE_STAGE_FIELDS

    check_date = new_date or selected['date']
    check_time = new_time or selected['time']

    ok, error_text = _check_update_availability(selected, appointments, check_date, check_time)
    if not ok:
        return [response_model.text_message(error_text)], _UPDATE_STAGE_FIELDS

    if selected.get('id'):
        pending = {"id": selected['id']}
    else:
        pending = {
            "name": selected['name'],
            "originalDate": selected['date'],
            "originalTime": selected['time'],
        }
    if new_date:
        pending['newDate'] = new_date
    if new_time:
        pending['newTime'] = new_time

    with open(PENDING_UPDATE_FILE, 'w') as f:
        json.dump(pending, f, indent=2)

    change_bits = []
    if new_date:
        change_bits.append(f"date to {new_date}")
    if new_time:
        change_bits.append(f"time to {new_time}")
    change_text = " and ".join(change_bits)

    text = (
        f"Please confirm — update the appointment for {selected['name']} "
        f"(currently {selected['date']} at {selected['time']}) to change {change_text}? (yes or no)"
    )
    return [response_model.text_message(text)], _UPDATE_STAGE_CONFIRM


def _handle_update_confirm_yes():
    """Confirms a pending update. Mirrors _handle_cancel_confirm_yes's own
    "never trust the initial snapshot, always re-verify fresh" discipline:
    re-reads appointments.json, re-identifies the exact intended
    appointment via _matches_pending_update() (never "first matching
    name"), confirms it is still active, and re-validates the proposed
    date/time against availability_service one more time (again excluding
    the appointment itself from its own conflict check) immediately
    before writing anything. Only `date`/`time` are ever assigned - every
    other field on the target dict is left exactly as read.
    """
    if not os.path.exists(PENDING_UPDATE_FILE):
        return [response_model.text_message("There is no update pending confirmation.")], None

    with open(PENDING_UPDATE_FILE, 'r') as f:
        pending = json.load(f)

    if not os.path.exists(APPOINTMENTS_FILE):
        os.remove(PENDING_UPDATE_FILE)
        text = "I couldn't find that appointment anymore. No changes were made."
        return [response_model.text_message(text)], None

    appointments = _read_appointments_raw()

    target = None
    for appointment in appointments:
        if _matches_pending_update(appointment, pending):
            target = appointment
            break

    if target is None or not _is_active(target):
        os.remove(PENDING_UPDATE_FILE)
        text = (
            "That appointment is no longer available to update - it may have already been "
            "cancelled or changed. No other appointment was affected."
        )
        return [response_model.text_message(text)], None

    new_date = pending.get('newDate')
    new_time = pending.get('newTime')
    check_date = new_date or target['date']
    check_time = new_time or target['time']

    ok, error_text = _check_update_availability(target, appointments, check_date, check_time)
    if not ok:
        os.remove(PENDING_UPDATE_FILE)
        text = (
            "Sorry, that time is no longer available - it looks like it was just taken. "
            "No changes were made; please start the update again."
        )
        return [response_model.text_message(text)], None

    if new_date:
        target['date'] = new_date
    if new_time:
        target['time'] = new_time

    _save_appointments(appointments)
    os.remove(PENDING_UPDATE_FILE)

    text = f"Your appointment for {target['name']} has been updated to {target['date']} at {target['time']}."
    return [response_model.text_message(text)], _UPDATE_STAGE_UPDATED


def _handle_update_confirm_no():
    if os.path.exists(PENDING_UPDATE_FILE):
        os.remove(PENDING_UPDATE_FILE)
        text = "No problem! I've left that appointment unchanged."
    else:
        text = "There is no update pending confirmation."
    return [response_model.text_message(text)], None


_CANCELLATION_STAGE_IDENTIFIER = "identifier"
_CANCELLATION_STAGE_CONFIRM = "confirm"
_CANCELLATION_STAGE_CANCELLED = "cancelled"


def _is_active(appointment):
    """An appointment with no `status` at all (every legacy record) is
    treated as active, matching availability_service.py's own convention
    for a missing status. Only an explicit `status == "cancelled"` is
    treated as inactive - this module doesn't validate `status` against a
    fixed set the way availability_service.py does, since that stricter
    validation belongs to slot-conflict reasoning, not to this feature.
    """
    return appointment.get('status') != 'cancelled'


def _describe_candidate(appointment):
    """One line of a disambiguation list - includes the id only when the
    candidate actually has one (never invents one for a legacy record).
    """
    parts = []
    if appointment.get('id'):
        parts.append(f"ID {appointment['id']}")
    parts.append(f"{appointment['date']} at {appointment['time']}")
    if appointment.get('providerId'):
        parts.append(f"provider {appointment['providerId']}")
    return "- " + ", ".join(parts)


def _matches_pending_cancellation(appointment, pending):
    """Re-identifies the exact appointment a pending cancellation refers
    to, without ever falling back to "first matching name" - see
    _handle_cancel_confirm_yes's docstring for why this matters. Prefers
    the stable `id` when the pending record has one; for a legacy no-id
    record, requires an exact match on name AND date AND time together
    (all three captured verbatim from the original record at selection
    time, not typed by the user), which is far more specific than name
    alone.
    """
    if 'id' in pending:
        return appointment.get('id') == pending['id']
    return (
        appointment.get('name') == pending.get('name')
        and appointment.get('date') == pending.get('date')
        and appointment.get('time') == pending.get('time')
    )


def _handle_cancel_appointment(parameters):
    """IDENTIFIER -> CONFIRM -> CANCELLED.

    Next Phase 6.1 slice: replaces the previous hard-delete-by-name
    cancellation with a safe, confirmed, ID-preferring flow. Returns
    (messages, cancellation_stage) - see response_model.success_response's
    docstring for the stage vocabulary.

    Lookup rules, in order:
      1. `parameters.id`, if given, must exactly match an ACTIVE
         appointment's `id`. No fallback to `name` if it doesn't - an
         explicitly supplied id is never silently reinterpreted.
      2. Otherwise `parameters.name` is matched case-insensitively
         against ACTIVE appointments only. Zero matches -> "not found".
         Exactly one match -> proceed. More than one match -> a
         deterministic disambiguation listing every candidate (id when
         available, date, time, providerId when available) and asking
         for the id - never guesses, never picks one. If any candidate in
         an ambiguous group lacks an id, disambiguation by id isn't
         possible for that group, so no candidate is selected and nothing
         is changed - never mutated or backfilled just because it was
         looked at.

    Nothing is written to appointments.json here - only a pending
    cancellation record (PENDING_CANCELLATION_FILE) once exactly one
    active appointment has been safely identified.
    """
    parameters = parameters or {}
    appointment_id = parameters.get('id')
    name = parameters.get('name')

    if not appointment_id and not name:
        text = "Sure - what's the ID or name on the appointment you'd like to cancel?"
        return [response_model.text_message(text)], _CANCELLATION_STAGE_IDENTIFIER

    if not os.path.exists(APPOINTMENTS_FILE):
        return [response_model.text_message("There are no appointments to cancel yet.")], None

    appointments = _read_appointments_raw()

    if appointment_id:
        selected = None
        for appointment in appointments:
            if appointment.get('id') == appointment_id:
                selected = appointment
                break
        if selected is None or not _is_active(selected):
            text = "I couldn't find an active appointment with that ID. Please check the ID and try again."
            return [response_model.text_message(text)], _CANCELLATION_STAGE_IDENTIFIER
        pending = {"id": appointment_id}
    else:
        candidates = [
            a for a in appointments
            if _is_active(a) and a.get('name', '').lower() == name.lower()
        ]
        if not candidates:
            text = f"I couldn't find an appointment for {name} to cancel."
            return [response_model.text_message(text)], None

        if len(candidates) > 1:
            lines = [_describe_candidate(a) for a in candidates]
            if any(not a.get('id') for a in candidates):
                text = (
                    f"I found multiple appointments for {name}, and at least one of them "
                    "doesn't have a reference ID yet, so I can't safely tell them apart. "
                    "Here they are - none have been changed:\n" + "\n".join(lines)
                )
                return [response_model.text_message(text)], _CANCELLATION_STAGE_IDENTIFIER

            text = (
                f"I found multiple appointments for {name}. Please tell me the appointment ID "
                "of the one you'd like to cancel:\n" + "\n".join(lines)
            )
            suggestions = [
                {"id": a["id"], "label": f"{a['date']} at {a['time']}", "value": a["id"]}
                for a in candidates
            ]
            return [response_model.text_message(text, suggestions=suggestions)], _CANCELLATION_STAGE_IDENTIFIER

        selected = candidates[0]
        if selected.get('id'):
            pending = {"id": selected['id']}
        else:
            pending = {"name": selected['name'], "date": selected['date'], "time": selected['time']}

    with open(PENDING_CANCELLATION_FILE, 'w') as f:
        json.dump(pending, f, indent=2)

    provider_bit = f" with {selected['providerId']}" if selected.get('providerId') else ""
    text = (
        f"Please confirm — cancel the appointment for {selected['name']} on {selected['date']} "
        f"at {selected['time']}{provider_bit}? (yes or no)"
    )
    return [response_model.text_message(text)], _CANCELLATION_STAGE_CONFIRM


def _handle_cancel_confirm_yes():
    """Confirms a pending cancellation. Mirrors _handle_yes_intent's own
    "never trust the initial snapshot, always re-verify fresh" discipline:
    re-reads appointments.json and re-identifies the exact intended
    appointment via _matches_pending_cancellation() - never by re-running
    a "first matching name" search - so a record that changed or vanished
    between the initial request and this confirmation is handled safely
    instead of silently affecting a different appointment.
    """
    if not os.path.exists(PENDING_CANCELLATION_FILE):
        return [response_model.text_message("There is no cancellation pending confirmation.")], None

    with open(PENDING_CANCELLATION_FILE, 'r') as f:
        pending = json.load(f)

    if not os.path.exists(APPOINTMENTS_FILE):
        os.remove(PENDING_CANCELLATION_FILE)
        text = "I couldn't find that appointment anymore. No changes were made."
        return [response_model.text_message(text)], None

    appointments = _read_appointments_raw()

    target = None
    for appointment in appointments:
        if _matches_pending_cancellation(appointment, pending):
            target = appointment
            break

    if target is None or not _is_active(target):
        os.remove(PENDING_CANCELLATION_FILE)
        text = (
            "That appointment is no longer available to cancel - it may have already been "
            "cancelled or changed. No other appointment was affected."
        )
        return [response_model.text_message(text)], None

    target['status'] = 'cancelled'
    _save_appointments(appointments)
    os.remove(PENDING_CANCELLATION_FILE)

    text = f"Your appointment for {target['name']} on {target['date']} at {target['time']} has been cancelled."
    return [response_model.text_message(text)], _CANCELLATION_STAGE_CANCELLED


def _handle_cancel_confirm_no():
    if os.path.exists(PENDING_CANCELLATION_FILE):
        os.remove(PENDING_CANCELLATION_FILE)
        text = "No problem! I've left that appointment unchanged."
    else:
        text = "There is no cancellation pending confirmation."
    return [response_model.text_message(text)], None


def _handle_view_appointments():
    """Next Phase 6.1 slice: excludes cancelled appointments from the
    normal active listing (a missing `status` still counts as active, for
    legacy records) and shows each active appointment's `id` when it has
    one - legacy no-id records still display exactly as before, just
    without an ID suffix.
    """
    if os.path.exists(APPOINTMENTS_FILE):
        try:
            appointments = _read_appointments_raw()
            active = [a for a in appointments if _is_active(a)]
            if active:
                response_lines = []
                for a in active:
                    line = f"{a['name']} on {a['date']} at {a['time']}"
                    if a.get('id'):
                        line += f" (ID: {a['id']})"
                    response_lines.append(line)
                text = "Here’s a quick look at your scheduled appointments:\n" + "\n".join(response_lines)
            else:
                text = "You don't have any appointments booked at the moment."
        except json.JSONDecodeError:
            text = "I'm having trouble reading your appointment records right now."
    else:
        text = "No appointment data found."

    return [response_model.text_message(text)]


_GENERAL_FAQ_GREETING = (
    "Hi! I'm your virtual healthcare assistant. I can help you check symptoms, "
    "book or cancel appointments, and answer general health-related questions. "
    "What would you like help with today?"
)


def _handle_general_faq(parameters, request_id=None):
    """General FAQ is the sole intent that reaches here with confidence
    "none" in the frontend's classifyIntent (see
    frontend/src/conversation/intent.js) - every other intent (booking,
    cancel, update, view, yes/no, symptom check) has its own dedicated,
    fully deterministic handler above and never reaches this function.
    That existing intent-dispatch boundary IS the LLM eligibility gate;
    no second classifier is introduced here.

    `parameters.get('message')` is the raw user question, if the caller
    provided one. The current frontend (useConversation.js) does not send
    this yet for General FAQ - see backend/LLM_ASSISTANT_NOTES.md - so in
    practice this still always falls back to the deterministic greeting
    below until that is wired up as a separate, explicit step.
    """
    message_text = (parameters or {}).get('message')

    if not llm_config.LLM_ENABLED or not message_text:
        return [response_model.text_message(_GENERAL_FAQ_GREETING)]

    result = assistant_service.answer(message_text, request_id=request_id)

    if result["allowed"] and result["source"] == "llm":
        return [response_model.assistant_response_message(
            result["text"], provider=result.get("provider", "claude")
        )]

    # Every refusal/failure path in assistant_service.answer() already
    # produces a safe, deterministic, non-leaking message - reuse it
    # directly rather than inventing a second fallback message here.
    return [response_model.text_message(result["text"])]
