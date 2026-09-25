"""Deterministic repository for provider and provider-availability data.

Phase 6.1, Slice 1 built this as a small, standalone foundation. Slice 3
wired it into the live booking flow: chatbot_logic.py's
_format_provider_list() and choose-provider handling call
list_providers() (via _handle_book_appointment), as part of the booking
sequence NAME -> PROVIDER -> DATE -> SLOT -> CONFIRM -> BOOKED. See
backend/PROVIDER_AVAILABILITY_NOTES.md for the full history and current
scope.

What this module WILL do:
  - Load and strictly validate backend/providers.json and
    backend/provider_availability.json.
  - Provide small, plain functions to look up a provider by id, list every
    provider, and get a provider's recurring weekly availability windows.
  - Fail loudly (ProviderDataError) on any malformed or inconsistent data -
    a duplicate provider id, a missing required field, an availability
    entry referencing an unknown provider, an invalid weekday, a malformed
    HH:MM time, endTime <= startTime, or a non-positive slotMinutes.

What this module WILL NOT do (deliberately out of scope for this slice):
  - Compute actual bookable time slots from an availability window - that
    is a later slice's slot-generation function, not this one.
  - Handle holidays, one-off exceptions, or any date-specific override to
    the recurring weekly schedule.
  - Do any timezone conversion. Every time in provider_availability.json is
    local clinic time, exactly as written - see PROVIDER_AVAILABILITY_NOTES.md.
  - Touch backend/appointments.json, chatbot_logic.py, or any conversation
    flow. This module only reads its own two JSON files.

File I/O is isolated to this module: both JSON files are read fresh on
every call when no explicit `providers`/`availability` argument is given,
matching the same "always read current data, never cache in memory"
convention already used by chatbot_logic.py (appointments.json) and
symptom_triage.py (symptom_rules.json).
"""
import json
import os
import re

PROVIDERS_FILE = os.path.join(os.path.dirname(__file__), 'providers.json')
AVAILABILITY_FILE = os.path.join(os.path.dirname(__file__), 'provider_availability.json')

_VALID_WEEKDAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)

_REQUIRED_PROVIDER_FIELDS = ("id", "name", "specialty", "location")
_REQUIRED_AVAILABILITY_FIELDS = ("providerId", "dayOfWeek", "startTime", "endTime", "slotMinutes")

_TIME_PATTERN = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')


class ProviderDataError(ValueError):
    """Raised when providers.json or provider_availability.json is missing,
    malformed, or invalid.

    Deliberately fails loudly rather than silently dropping a bad entry or
    continuing with partial/inconsistent data - matches
    symptom_triage.SymptomRuleError's convention, for the same reason: for
    a healthcare-adjacent scheduling feature, a loud startup/load failure
    is far preferable to silently-wrong provider or availability data.
    """


def _validate_provider(provider, index):
    if not isinstance(provider, dict):
        raise ProviderDataError(f"providers[{index}] must be an object, got {type(provider).__name__}")

    for field in _REQUIRED_PROVIDER_FIELDS:
        if field not in provider:
            raise ProviderDataError(
                f"providers[{index}] ({provider.get('id', '?')!r}) is missing required field {field!r}"
            )
        value = provider[field]
        if not isinstance(value, str) or not value.strip():
            raise ProviderDataError(
                f"providers[{index}] ({provider.get('id', '?')!r}) has an invalid {field!r} - "
                "must be a non-empty string"
            )


def load_providers(path=None):
    """Loads and strictly validates providers.json.

    Raises ProviderDataError on a missing file, invalid JSON, a non-list
    top-level value, a provider missing/mistyping a required field, or a
    duplicate provider id. Never silently drops a bad entry or returns a
    partial list.
    """
    file_path = path or PROVIDERS_FILE

    if not os.path.exists(file_path):
        raise ProviderDataError(f"providers file not found: {file_path}")

    with open(file_path, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ProviderDataError(f"providers file is not valid JSON: {e}") from e

    if not isinstance(data, list):
        raise ProviderDataError("providers file must contain a JSON array")

    seen_ids = set()
    for index, provider in enumerate(data):
        _validate_provider(provider, index)
        provider_id = provider["id"]
        if provider_id in seen_ids:
            raise ProviderDataError(f"duplicate provider id: {provider_id!r}")
        seen_ids.add(provider_id)

    return data


def list_providers(providers=None):
    """Returns every known provider, in file order.

    Loads providers.json fresh when `providers` isn't supplied.
    """
    if providers is None:
        providers = load_providers()
    return list(providers)


def find_provider(provider_id, providers=None):
    """Returns the provider dict with this id, or None if there isn't one.

    Deliberately returns None rather than raising for an unknown id - an
    unrecognized id is an ordinary "not found" outcome for a caller to
    handle, not a data-integrity problem (that's what load_providers()'s
    validation is for).
    """
    if providers is None:
        providers = load_providers()
    for provider in providers:
        if provider["id"] == provider_id:
            return provider
    return None


def _parse_time_to_minutes(value, context):
    if not isinstance(value, str) or not _TIME_PATTERN.match(value):
        raise ProviderDataError(f"{context} is not a valid HH:MM time: {value!r}")
    hours, minutes = value.split(':')
    return int(hours) * 60 + int(minutes)


def _validate_availability_entry(entry, index, known_provider_ids):
    if not isinstance(entry, dict):
        raise ProviderDataError(f"availability[{index}] must be an object, got {type(entry).__name__}")

    for field in _REQUIRED_AVAILABILITY_FIELDS:
        if field not in entry:
            raise ProviderDataError(f"availability[{index}] is missing required field {field!r}")

    provider_id = entry["providerId"]
    if not isinstance(provider_id, str) or not provider_id.strip():
        raise ProviderDataError(
            f"availability[{index}] has an invalid 'providerId' - must be a non-empty string"
        )
    if provider_id not in known_provider_ids:
        raise ProviderDataError(f"availability[{index}] references unknown providerId {provider_id!r}")

    day = entry["dayOfWeek"]
    if day not in _VALID_WEEKDAYS:
        raise ProviderDataError(
            f"availability[{index}] ({provider_id!r}) has an invalid 'dayOfWeek' {day!r} - "
            f"must be one of {_VALID_WEEKDAYS}"
        )

    start_minutes = _parse_time_to_minutes(
        entry["startTime"], f"availability[{index}] ({provider_id!r}) 'startTime'"
    )
    end_minutes = _parse_time_to_minutes(
        entry["endTime"], f"availability[{index}] ({provider_id!r}) 'endTime'"
    )
    if start_minutes >= end_minutes:
        raise ProviderDataError(
            f"availability[{index}] ({provider_id!r}) has 'startTime' that is not before 'endTime' "
            f"({entry['startTime']!r} >= {entry['endTime']!r})"
        )

    slot_minutes = entry["slotMinutes"]
    if not isinstance(slot_minutes, int) or isinstance(slot_minutes, bool) or slot_minutes <= 0:
        raise ProviderDataError(
            f"availability[{index}] ({provider_id!r}) has an invalid 'slotMinutes' {slot_minutes!r} - "
            "must be a positive integer"
        )


def load_availability(path=None, providers=None):
    """Loads and strictly validates provider_availability.json.

    Cross-validates every entry's providerId against load_providers() (or
    the given `providers` list), so a typo'd or removed provider id is
    caught at load time instead of silently producing availability for a
    nonexistent provider. Raises ProviderDataError on a missing file,
    invalid JSON, a non-list top-level value, or any invalid entry
    (unknown providerId, invalid dayOfWeek, malformed HH:MM time, endTime
    not after startTime, or a non-positive slotMinutes).
    """
    file_path = path or AVAILABILITY_FILE

    if not os.path.exists(file_path):
        raise ProviderDataError(f"provider availability file not found: {file_path}")

    with open(file_path, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ProviderDataError(f"provider availability file is not valid JSON: {e}") from e

    if not isinstance(data, list):
        raise ProviderDataError("provider availability file must contain a JSON array")

    if providers is None:
        providers = load_providers()
    known_provider_ids = {provider["id"] for provider in providers}

    for index, entry in enumerate(data):
        _validate_availability_entry(entry, index, known_provider_ids)

    return data


def get_provider_availability(provider_id, availability=None):
    """Returns every availability window for `provider_id`, in file order.

    Does not itself check whether provider_id is a real, known provider -
    an id with no matching entries simply returns an empty list, the same
    "not found -> empty/None, not an exception" pattern find_provider()
    uses. Callers that need to confirm the provider itself exists should
    call find_provider() as well.
    """
    if availability is None:
        availability = load_availability()
    return [entry for entry in availability if entry["providerId"] == provider_id]


def validate_all(providers_path=None, availability_path=None):
    """Loads and validates both files together as a single startup/CI
    check. Returns (providers, availability) on success; raises
    ProviderDataError on the first problem found in either file.
    """
    providers = load_providers(providers_path)
    availability = load_availability(availability_path, providers=providers)
    return providers, availability
