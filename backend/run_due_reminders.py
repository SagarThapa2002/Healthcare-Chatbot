"""CLI execution boundary for the due-reminder processor (Phase 6.2-D).

    external scheduler (future: cron / launchd / a cloud job runner)
        |
        v
    python -m backend.run_due_reminders
        |
        v
    reminder_service.get_due_reminders() / process_due_reminders(...)
        |
        v
    future notification sender (not built yet)

This module owns ONLY the command-line boundary: argument parsing, exit
codes, and metadata-only logging. It deliberately owns NONE of the
domain logic - reminder eligibility, scheduling, state transitions, and
appointment lookup all remain exactly where they already are, in
backend/reminder_service.py (and, for eligibility/scheduling,
backend/reminder_config.py). This module never reaches into
reminders.json/appointments.json directly, and never computes a status
transition itself - it only calls the existing, already-tested
reminder_service functions and reports their outcome.

No real notification provider exists yet (see REMINDER_NOTES.md's Phase
6.2-D section) - `python -m backend.run_due_reminders` (with no flags)
therefore refuses to run a mutating pass at all, deterministically and
safely, rather than fabricating a "sent" outcome with nothing actually
delivered. Use `--dry-run` to see how many reminders are currently due
without processing or mutating anything.

Logging follows this project's existing metadata-only policy (see
backend/LOGGING_NOTES.md): only aggregate counts and exception *type*
names are ever logged here - never appointment names/dates/times,
reminder ids, notification content, or contact details, and never a raw
exception message (which could echo reminder/appointment data).
"""
import argparse
import logging
import os
import sys

from backend import reminder_service

logger = logging.getLogger(__name__)

# Exit codes - deterministic and stable, so a future scheduler (cron,
# launchd, a cloud job runner - see REMINDER_NOTES.md) can alert on them
# without needing to parse any log output.
EXIT_OK = 0
EXIT_MALFORMED_DATA = 1
EXIT_RUNTIME_FAILURE = 2
EXIT_NO_SENDER_CONFIGURED = 3


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


def _run_mutating():
    """No real notification sender/provider exists yet (see
    REMINDER_NOTES.md's Phase 6.2-D section) - marking reminders as `sent`
    with nothing actually delivered would write false, misleading
    records into reminders.json. Fails safely and clearly instead of
    fabricating delivery: process_due_reminders() is deliberately never
    called here, so nothing in reminders.json or appointments.json is
    ever touched by this path. This is intentionally the ONLY thing this
    function does, so it is trivial to replace once a real sender exists
    - at that point this becomes "construct the configured sender, call
    reminder_service.process_due_reminders(send=that_sender)", and
    nothing else in this module needs to change.
    """
    logger.error(
        "no notification sender is configured - refusing to run a mutating "
        "pass (exit_code=%d) - see backend/REMINDER_NOTES.md, Phase 6.2-D",
        EXIT_NO_SENDER_CONFIGURED,
    )
    return EXIT_NO_SENDER_CONFIGURED


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
