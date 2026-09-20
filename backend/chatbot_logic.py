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

from backend import assistant_service
from backend import availability_service
from backend import llm_config
from backend import provider_repository
from backend import response_model

logger = logging.getLogger(__name__)

APPOINTMENTS_FILE = os.path.join(os.path.dirname(__file__), 'appointments.json')
PENDING_FILE = os.path.join(os.path.dirname(__file__), 'pending_appointments.json')


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

    if intent == "Symptom Check":
        messages = _handle_symptom_check(parameters)
    elif intent == "Book Appointment":
        messages = _handle_book_appointment(parameters)
    elif intent == "YesIntent":
        messages = _handle_yes_intent()
    elif intent == "NoIntent":
        messages = _handle_no_intent()
    elif intent == "Update Appointment":
        messages = _handle_update_appointment(parameters)
    elif intent == "Cancel Appointment":
        messages = _handle_cancel_appointment(parameters)
    elif intent == "View Appointments":
        messages = _handle_view_appointments()
    elif intent == "General FAQ":
        messages = _handle_general_faq(parameters, request_id=request_id)
    else:
        messages = [response_model.text_message(
            "Sorry, I didn't understand that. Could you rephrase or ask something else?"
        )]

    return response_model.success_response(messages, intent=intent, request_id=request_id)


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
    """
    parameters = parameters or {}
    name = parameters.get('name')
    provider_choice = parameters.get('providerId')
    date = parameters.get('date')
    slot_choice = parameters.get('time')

    if not name:
        text = "Sure, may I have your name for the appointment?"
        return [response_model.text_message(text)]

    if not provider_choice:
        text = f"Thanks {name}. Which provider would you like to see?\n{_format_provider_list()}"
        return [response_model.text_message(text)]

    provider_id = _resolve_provider_choice(provider_choice)
    if provider_id is None:
        text = (
            "Sorry, I didn't recognize that provider. Please choose one from the list:\n"
            f"{_format_provider_list()}"
        )
        return [response_model.text_message(text)]

    if not date:
        provider = provider_repository.find_provider(provider_id)
        provider_name = provider["name"] if provider else provider_id
        text = f"What date would you like to see {provider_name}? (YYYY-MM-DD)"
        return [response_model.text_message(text)]

    try:
        status, _ = _check_date_availability(provider_id, date)
    except availability_service.AvailabilityError as e:
        logger.warning(
            "booking date availability check failed provider_id=%s exception_type=%s",
            provider_id, type(e).__name__,
        )
        text = "I couldn't check availability for that date. Could you give me a date in YYYY-MM-DD format?"
        return [response_model.text_message(text)]

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
        return [response_model.text_message(text)]

    if status == _DATE_FULLY_BOOKED:
        text = f"{provider_name} is fully booked on {date}. Could you try a different date?"
        return [response_model.text_message(text)]

    # status == _DATE_HAS_SLOTS
    if not slot_choice:
        text = f"Here are the available times on {date}:\n{_format_slot_list(provider_id, date)}"
        return [response_model.text_message(text)]

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
        return [response_model.text_message(text)]

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

    return [response_model.text_message(text)]


def _handle_yes_intent():
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, 'r') as f:
            appointment = json.load(f)

        appointments = []
        if os.path.exists(APPOINTMENTS_FILE):
            try:
                appointments = _read_appointments_raw()
            except json.JSONDecodeError:
                appointments = []

        appointments.append(appointment)
        _save_appointments(appointments)
        os.remove(PENDING_FILE)

        text = f"Your appointment for {appointment['name']} on {appointment['date']} at {appointment['time']} has been booked."
        return [response_model.booking_confirmation_message(text, appointment)]

    text = "There is no appointment pending confirmation."
    return [response_model.text_message(text)]


def _handle_no_intent():
    if os.path.exists(PENDING_FILE):
        os.remove(PENDING_FILE)
        text = "No problem! Appointment booking has been canceled. Let me know if you'd like to try again."
    else:
        text = "There is no pending appointment to cancel."
    return [response_model.text_message(text)]


def _handle_update_appointment(parameters):
    name = (parameters or {}).get('name')
    if not name:
        return [response_model.text_message(
            "Sure - what's the name on the appointment you'd like to update?"
        )]

    new_date = parameters.get('date')
    new_time = parameters.get('time')

    if os.path.exists(APPOINTMENTS_FILE):
        appointments = _read_appointments_raw()

        updated = False
        for appointment in appointments:
            if appointment['name'].lower() == name.lower():
                if new_date:
                    appointment['date'] = new_date
                if new_time:
                    appointment['time'] = new_time
                updated = True
                break

        if updated:
            _save_appointments(appointments)
            text = f"Your appointment for {name} has been updated."
        else:
            text = f"I couldn't find an appointment for {name}."
    else:
        text = "There are no appointments to update yet."

    return [response_model.text_message(text)]


def _handle_cancel_appointment(parameters):
    name = (parameters or {}).get('name')
    if not name:
        return [response_model.text_message(
            "Sure - what's the name on the appointment you'd like to cancel?"
        )]

    if os.path.exists(APPOINTMENTS_FILE):
        appointments = _read_appointments_raw()

        original_length = len(appointments)
        appointments = [a for a in appointments if a['name'].lower() != name.lower()]
        _save_appointments(appointments)

        if len(appointments) < original_length:
            text = f"Your appointment for {name} has been successfully canceled."
        else:
            text = f"I couldn't find an appointment for {name} to cancel."
    else:
        text = "There are no appointments to cancel yet."

    return [response_model.text_message(text)]


def _handle_view_appointments():
    if os.path.exists(APPOINTMENTS_FILE):
        try:
            appointments = _read_appointments_raw()
            if appointments:
                response_lines = [f"{a['name']} on {a['date']} at {a['time']}" for a in appointments]
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
