"""Configuration for the appointment reminder feature (Phase 6.2-A).

`CLINIC_TIMEZONE` is read from the environment fresh on every call, with
NO fallback default and NO validation at import time - deliberately
different from backend/llm_config.py's style, where every setting has a
safe default. A wrong or silently-defaulted LLM setting degrades
observably (a bad model name errors from the API; a bad timeout just
times out sooner); a wrong or silently-defaulted clinic timezone would
systematically mis-time every reminder by a fixed offset with nothing to
ever surface the mistake. That is exactly the class of failure this
project already refuses to allow elsewhere - see
backend/provider_repository.py's ProviderDataError and
backend/availability_service.py's AvailabilityError, both of which fail
loudly on bad configuration/data rather than guessing. ReminderConfigError
is the same discipline applied to timezone configuration.

Validation happens only when reminder scheduling is actually attempted
(get_clinic_timezone(), called from reminder_service.compute_send_at()) -
never at import time - so simply importing this module (or
reminder_service.py) can never crash the app before any reminder feature
is actually used.
"""
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The env var name itself - not a default value. There is deliberately no
# corresponding DEFAULT_CLINIC_TIMEZONE constant anywhere in this module.
CLINIC_TIMEZONE_ENV_VAR = "CLINIC_TIMEZONE"


class ReminderConfigError(ValueError):
    """Raised when CLINIC_TIMEZONE is missing, blank, or not a valid IANA
    timezone name recognized by the system's tzdata.

    Never raised for a data problem with a specific appointment or
    reminder record - that is reminder_service.ReminderDataError's job.
    This is exclusively about the reminder feature's own configuration.
    """


def get_clinic_timezone():
    """Returns a zoneinfo.ZoneInfo for the configured CLINIC_TIMEZONE.

    Reads the environment fresh on every call - no caching - matching the
    "always read current configuration/data, never cache in memory"
    convention already used throughout this project (chatbot_logic.py's
    appointments.json, provider_repository.py's own two JSON files).

    zoneinfo.ZoneInfo() looks up a named zone from tzdata only - it never
    consults the operating system's local/default timezone (unlike a bare
    `datetime.now()`, which does) - so this can never silently depend on
    wherever the process happens to be running. Confirmed empirically
    during this slice's design phase: setting the process's own `TZ`
    environment variable has no effect on the zone this function returns
    (see test_reminder_config.py's own test for this).

    Raises ReminderConfigError if CLINIC_TIMEZONE is unset, blank, or not
    a valid IANA timezone name - never falls back to UTC, the server's OS
    timezone, or any other guess.
    """
    name = os.environ.get(CLINIC_TIMEZONE_ENV_VAR)
    if not name or not name.strip():
        raise ReminderConfigError(
            f"{CLINIC_TIMEZONE_ENV_VAR} is not set. Reminder scheduling requires an "
            "explicit IANA timezone name (e.g. 'Europe/London') - there is no default."
        )

    normalized = name.strip()
    try:
        return ZoneInfo(normalized)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ReminderConfigError(
            f"{CLINIC_TIMEZONE_ENV_VAR}={normalized!r} is not a valid IANA timezone name."
        ) from e
