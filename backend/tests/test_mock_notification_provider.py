"""Tests for backend/mock_notification_provider.py (Phase 6.2-E).

These tests exercise mock_notification_provider.send() directly, in
isolation - never through the CLI or reminder_service.process_due_reminders()
(that end-to-end wiring is covered by backend/tests/test_run_due_reminders.py).
The goal here is narrower: prove this module's own contract - deterministic
outcome by reminder id marker, no mutation of either argument, no network
dependency, and no dependence on appointment content whatsoever.
"""
import copy
import inspect
import unittest

from backend import mock_notification_provider as provider


def make_reminder(reminder_id="r1"):
    return {
        "id": reminder_id,
        "appointmentId": "a1",
        "type": "24h_before",
        "sendAt": "2026-12-01T00:00:00+00:00",
        "status": "pending",
        "createdAt": "2026-11-01T00:00:00+00:00",
        "sentAt": None,
        "failureReason": None,
    }


def make_appointment():
    return {
        "id": "a1",
        "name": "Test Patient",
        "date": "2026-12-02",
        "time": "10:00",
        "providerId": "p1",
        "durationMinutes": 30,
    }


class DeterministicOutcomeTest(unittest.TestCase):
    def test_plain_id_succeeds(self):
        self.assertTrue(provider.send(make_reminder("r1"), make_appointment()))

    def test_failure_marker_returns_false(self):
        reminder_id = f"r1{provider.MOCK_FAILURE_MARKER}"
        self.assertFalse(provider.send(make_reminder(reminder_id), make_appointment()))

    def test_error_marker_raises_mock_notification_error(self):
        reminder_id = f"r1{provider.MOCK_ERROR_MARKER}"
        with self.assertRaises(provider.MockNotificationError):
            provider.send(make_reminder(reminder_id), make_appointment())


class NoMutationTest(unittest.TestCase):
    def test_reminder_not_mutated_on_success(self):
        reminder = make_reminder("r1")
        before = copy.deepcopy(reminder)
        provider.send(reminder, make_appointment())
        self.assertEqual(reminder, before)

    def test_reminder_not_mutated_on_failure(self):
        reminder = make_reminder(f"r1{provider.MOCK_FAILURE_MARKER}")
        before = copy.deepcopy(reminder)
        provider.send(reminder, make_appointment())
        self.assertEqual(reminder, before)

    def test_reminder_not_mutated_on_exception(self):
        reminder = make_reminder(f"r1{provider.MOCK_ERROR_MARKER}")
        before = copy.deepcopy(reminder)
        with self.assertRaises(provider.MockNotificationError):
            provider.send(reminder, make_appointment())
        self.assertEqual(reminder, before)

    def test_appointment_not_mutated(self):
        appointment = make_appointment()
        before = copy.deepcopy(appointment)
        provider.send(make_reminder("r1"), appointment)
        self.assertEqual(appointment, before)


class NoContentOrNetworkDependenceTest(unittest.TestCase):
    def test_appointment_content_is_never_read(self):
        # If send() ever dereferenced `appointment` (a .get/[]/attribute
        # access), passing None here would raise - proving appointment
        # content never influences, and is never read to produce, this
        # provider's outcome or any patient/clinical content.
        self.assertTrue(provider.send(make_reminder("r1"), None))

    def test_no_network_or_notification_sdk_dependency_in_source(self):
        source = inspect.getsource(provider)
        for forbidden in ("socket", "requests", "urllib", "http.client", "smtplib", "anthropic"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
