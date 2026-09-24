"""CLI execution boundary for the due-reminder processor (Phase 6.2-D/E).

    external scheduler (future: cron / launchd / a cloud job runner)
        |
        v
    python -m backend.run_due_reminders
        |
        v
    reminder_service.get_due_reminders() / process_due_reminders(...)
        |
        v
    send(reminder, appointment) -> bool   (selected via NOTIFICATION_PROVIDER)
        |-- unset/unrecognized -> refuse (EXIT_NO_SENDER_CONFIGURED, the default)
        \\-- "mock"              -> backend.mock_notification_provider.send (Phase 6.2-E)

This module owns ONLY the command-line boundary: argument parsing,
notification-provider *selection* (never implementation), exit codes,
and metadata-only logging. It deliberately owns NONE of the domain
logic - reminder eligibility, scheduling, state transitions, and
appointment lookup all remain exactly where they already are, in
backend/reminder_service.py (and, for eligibility/scheduling,
backend/reminder_config.py). This module never reaches into
reminders.json/appointments.json directly, and never computes a status
transition itself - it only calls the existing, already-tested
reminder_service functions and reports their outcome.

No real (email/SMS/etc.) notification provider exists yet (see
REMINDER_NOTES.md's Phase 6.2-E section) - `python -m
backend.run_due_reminders` with no NOTIFICATION_PROVIDER configured
therefore still refuses to run a mutating pass at all, deterministically
and safely, rather than fabricating a "sent" outcome with nothing
actually delivered. This default is unchanged from Phase 6.2-D. Setting
`NOTIFICATION_PROVIDER=mock` opts into a deterministic, dependency-free,
non-network mock provider (backend/mock_notification_provider.py) that
exercises the real pipeline end-to-end without ever sending anything
externally - see that module's own docstring. Any other value, or the
variable being unset/blank, is treated identically to "no provider
configured" - never a silent fallback to the mock, and there is no real
provider to silently fall back to either. Use `--dry-run` to see how
many reminders are currently due without processing, mutating, or
invoking any sender at all.

Logging follows this project's existing metadata-only policy (see
backend/LOGGING_NOTES.md): only aggregate counts, provider-selection
*state* (configured vs. not - never the raw environment variable value),
and exception *type* names are ever logged here - never appointment
names/dates/times, reminder ids, notification content, or contact
details, and never a raw exception message (which could echo
reminder/appointment data).
"""
import argparse
import logging
import os
import sys

from backend import mock_notification_provider
from backend import reminder_service

logger = logging.getLogger(__name__)

# Exit codes - deterministic and stable, so a future scheduler (cron,
# launchd, a cloud job runner - see REMINDER_NOTES.md) can alert on them
# without needing to parse any log output.
EXIT_OK = 0
EXIT_MALFORMED_DATA = 1
EXIT_RUNTIME_FAILURE = 2
EXIT_NO_SENDER_CONFIGURED = 3

# Phase 6.2-E: the only environment variable this module reads to select a
# notification sender. Its own raw value is never logged (see this
# module's docstring and REMINDER_NOTES.md's Phase 6.2-E section).
NOTIFICATION_PROVIDER_ENV_VAR = "NOTIFICATION_PROVIDER"
NOTIFICATION_PROVIDER_MOCK = "mock"


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m backend.run_due_reminders",
        description=(
            "CLI execution boundary for backend.reminder_service's due-reminder "
            "processor. Owns no reminder domain logic of its own."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Report how many reminders are currently due, without processing "
            "or mutating anything (no sender is invoked, reminders.json and "
            "appointments.json are never written)."
        ),
    )
    return parser


def _run_dry_run():
    """Read-only: calls only get_due_reminders() (never process_due_reminders()),
    so nothing is ever mutated and no sender is ever invoked. Reports a
    single safe aggregate count - never per-reminder detail.
    """
    try:
        due = reminder_service.get_due_reminders()
    except reminder_service.ReminderDataError as e:
        logger.error(
            "dry run aborted - malformed reminder data - exception_type=%s", type(e).__name__
        )
        return EXIT_MALFORMED_DATA
    except Exception as e:
        logger.error(
            "dry run aborted - runtime failure - exception_type=%s", type(e).__name__
        )
        return EXIT_RUNTIME_FAILURE

    logger.info("Due reminders: %d", len(due))
    return EXIT_OK


def _select_sender():
    """Returns a `send(reminder, appointment) -> bool` callable selected by
    the NOTIFICATION_PROVIDER environment variable, or None if none is
    configured.

    Only the exact value "mock" (case-insensitive, surrounding whitespace
    ignored) selects backend.mock_notification_provider.send - Phase
    6.2-E's deterministic, non-network, dependency-free provider (see its
    own module docstring). The variable being unset, blank, or set to any
    other value all return None identically - there is no real provider
    to select yet, and an unrecognized value must never silently select
    the mock either (this is the opposite fail-safe direction from
    backend/llm_config.PROVIDER's own "unrecognized falls back to the
    real integration" convention - see REMINDER_NOTES.md's Phase 6.2-E
    section for why). Never logs the raw environment variable value.
    """
    value = os.environ.get(NOTIFICATION_PROVIDER_ENV_VAR, "").strip().lower()
    if value == NOTIFICATION_PROVIDER_MOCK:
        return mock_notification_provider.send
    return None


def _run_mutating():
    """Selects a notification sender from configuration (see
    _select_sender) and, only if one is configured, calls the REAL
    reminder_service.process_due_reminders(send=sender) - never a stub,
    never reimplemented here. No real (email/SMS/etc.) notification
    provider exists yet (see REMINDER_NOTES.md's Phase 6.2-E section), so
    with no NOTIFICATION_PROVIDER configured (or an unrecognized value)
    this refuses immediately and deterministically
    (EXIT_NO_SENDER_CONFIGURED) without calling process_due_reminders()
    or even get_due_reminders() - nothing in reminders.json or
    appointments.json is touched by that path, unchanged from Phase
    6.2-D. Marking reminders as `sent` with nothing actually delivered
    would write false, misleading records into reminders.json, so this
    refusal stays the default until a sender is explicitly configured.

    A completed processing run is reported as EXIT_OK even when
    individual reminders end up `failed`/`cancelled` - those are already
    correctly-modeled outcomes inside reminder_service.py (see
    process_due_reminders()'s own docstring), not a CLI-level failure.
    Only a failure of the *whole run* - malformed reminder data
    (ReminderDataError) or any other runtime failure - produces a
    non-zero exit here, exactly mirroring _run_dry_run()'s own exception
    handling and exit-code mapping.
    """
    sender = _select_sender()
    if sender is None:
        logger.error(
            "no notification provider is configured - refusing to run a mutating "
            "pass (exit_code=%d) - see backend/REMINDER_NOTES.md, Phase 6.2-E",
            EXIT_NO_SENDER_CONFIGURED,
        )
        return EXIT_NO_SENDER_CONFIGURED

    try:
        processed = reminder_service.process_due_reminders(send=sender)
    except reminder_service.ReminderDataError as e:
        logger.error(
            "reminder processing aborted - malformed reminder data - exception_type=%s",
            type(e).__name__,
        )
        return EXIT_MALFORMED_DATA
    except Exception as e:
        logger.error(
            "reminder processing aborted - runtime failure - exception_type=%s",
            type(e).__name__,
        )
        return EXIT_RUNTIME_FAILURE

    logger.info("Reminders processed: %d", len(processed))
    return EXIT_OK


def main(argv=None):
    """Parses arguments and dispatches to the dry-run or mutating path.

    `argv`, if given, is passed straight through to
    argparse.ArgumentParser.parse_args() - when None (the normal case for
    `python -m backend.run_due_reminders`), argparse falls back to its
    own standard `sys.argv[1:]` behavior. Returns an integer exit code
    (see the EXIT_* constants above) - never raises; every exception this
    function's own callees can produce is caught and mapped to a safe,
    logged, non-zero exit code.
    """
    args = _build_parser().parse_args(argv)

    if args.dry_run:
        return _run_dry_run()
    return _run_mutating()


if __name__ == "__main__":
    # Only configured when actually run as a script - matches app.py's
    # own logging.basicConfig call exactly (same LOG_LEVEL env var, same
    # format), so main() itself has no logging-configuration side effect
    # when imported/tested directly.
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    sys.exit(main())
