"""Deterministic mock notification provider (Phase 6.2-E).

FOR LOCAL/DEMO/TEST USE ONLY. Never makes a network call, never reads a
secret, never requires or reads any contact/destination information, and
never sends a real notification anywhere. Implements the existing
delivery seam exactly as reminder_service.process_due_reminders() already
defines it - `send(reminder, appointment) -> bool` - with no signature
change, no Protocol/ABC, and no result object (see backend/REMINDER_NOTES.md's
Phase 6.2-E section for why those remain deferred).

This module exists solely to exercise the real pipeline end-to-end - CLI
-> reminder_service.process_due_reminders() -> send() -> a real terminal
state persisted to reminders.json - not to simulate a realistic delivery.
It never reads, renders, or logs any patient-facing message content (no
message-template service exists yet - see REMINDER_NOTES.md) and never
inspects `appointment` at all - only `reminder["id"]` is ever read.

Deterministic behavior is controlled entirely by the reminder's own `id`
(never by appointment content, and never by real environment/network
state) - see MOCK_FAILURE_MARKER / MOCK_ERROR_MARKER below. A reminder id
containing neither marker always succeeds - real reminder ids are
UUIDs (backend/reminder_service.py's create_reminder()), which will never
contain either marker, so ordinary CLI/demo usage is unambiguous,
deterministic, always-succeeds behavior, not test-dependent guessing.
"""
import logging

logger = logging.getLogger(__name__)

# Substrings a test can embed in a reminder's own `id` to deterministically
# request the corresponding outcome from send() below - the smallest
# explicit control mechanism available without changing the reminder
# schema (no `channel`/contact field) or the send() signature itself.
MOCK_FAILURE_MARKER = "__mock_fail__"
MOCK_ERROR_MARKER = "__mock_error__"


class MockNotificationError(Exception):
    """Raised by send() only when a reminder's id is deliberately marked
    with MOCK_ERROR_MARKER (see module docstring) - exercises
    reminder_service.process_due_reminders()'s own per-reminder exception
    isolation (Phase 6.2-C), never a real delivery failure.
    """


def send(reminder, appointment):
    """Matches reminder_service.process_due_reminders()'s
    `send(reminder, appointment) -> bool` contract exactly.

    Reads only `reminder["id"]` - `appointment` is accepted (to match the
    contract) but never inspected, so no appointment/patient content of
    any kind ever influences, or is exposed by, this function. Never
    mutates either argument. Never raises for any input except a reminder
    id deliberately containing MOCK_ERROR_MARKER. Logs only a fixed,
    safe outcome label - never any reminder/appointment field value.
    """
    reminder_id = reminder.get("id") or ""

    if MOCK_ERROR_MARKER in reminder_id:
        logger.debug("mock notification provider: forced exception")
        raise MockNotificationError("mock notification provider: forced exception")

    if MOCK_FAILURE_MARKER in reminder_id:
        logger.debug("mock notification provider: forced failure")
        return False

    logger.debug("mock notification provider: forced success")
    return True
