"""Tests for backend/reminder_service.py (Phase 6.2-A and 6.2-B), plus
integration tests proving chatbot_logic.py's three reminder hooks
(_schedule_reminder_for_booking / _reschedule_reminders / _cancel_reminders)
are actually wired up.

Every test isolates reminders.json (and, for the integration classes,
appointments.json and the three pending-transaction files) to a temp
directory - never the real files - and sets an explicit, fixed
CLINIC_TIMEZONE for the duration of each test, never relying on whatever
happens to be set in the real environment running this suite.
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from app import app
from backend import availability_service, chatbot_logic, reminder_config, reminder_service


def make_appointment(**overrides):
    appointment = {
        "id": "appt-1",
        "name": "Test Patient",
        "providerId": "dr-patel",
        "date": "2026-12-28",
        "time": "10:00",
    }
    appointment.update(overrides)
    return appointment


class ReminderServiceTestCase(unittest.TestCase):
    """Base for reminder_service.py's own unit tests - isolates
    reminders.json to a temp file and sets a real, fixed CLINIC_TIMEZONE.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.reminders_file = os.path.join(self.tmp_dir.name, 'reminders.json')

        patcher = patch.dict('os.environ', {'CLINIC_TIMEZONE': 'Europe/London'}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _read_reminders(self):
        with open(self.reminders_file, 'r') as f:
            return json.load(f)


class ComputeSendAtTest(ReminderServiceTestCase):
    def test_normal_future_appointment_utc_conversion(self):
        # 2026-07-15 is summer - Europe/London is BST (UTC+1).
        appt = make_appointment(date="2026-07-15", time="10:00")
        send_at = reminder_service.compute_send_at(appt)
        self.assertEqual(send_at, datetime(2026, 7, 14, 9, 0, tzinfo=timezone.utc))

    def test_winter_no_dst_offset(self):
        appt = make_appointment(date="2026-12-28", time="10:00")
        send_at = reminder_service.compute_send_at(appt)
        self.assertEqual(send_at, datetime(2026, 12, 27, 10, 0, tzinfo=timezone.utc))

    def test_dst_boundary_uses_real_24_hour_subtraction_not_calendar_day(self):
        # Independently verified during design (see REMINDER_NOTES.md):
        # correct sendAt = 2026-03-28T23:30:00+00:00. A naive "subtract
        # one calendar day in local wall-clock time" would have produced
        # 2026-03-29T00:30:00+00:00 instead - 30 minutes wrong, since
        # March 28 is still GMT (UTC+0) while March 29-30 are already
        # BST (UTC+1, clocks go forward on the last Sunday of March).
        appt = make_appointment(date="2026-03-30", time="00:30")
        send_at = reminder_service.compute_send_at(appt)
        self.assertEqual(send_at, datetime(2026, 3, 28, 23, 30, tzinfo=timezone.utc))
        self.assertNotEqual(send_at, datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc))

    def test_invalid_date_returns_none_without_touching_timezone_config(self):
        appt = make_appointment(date="2026-02-30", time="10:00")  # not a real calendar date
        with patch.dict('os.environ', {}, clear=True):
            send_at = reminder_service.compute_send_at(appt)
        self.assertIsNone(send_at)

    def test_invalid_time_returns_none_without_touching_timezone_config(self):
        appt = make_appointment(date="2026-12-28", time="25:99")
        with patch.dict('os.environ', {}, clear=True):
            send_at = reminder_service.compute_send_at(appt)
        self.assertIsNone(send_at)

    def test_missing_timezone_raises_for_an_otherwise_valid_appointment(self):
        appt = make_appointment()
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(reminder_config.ReminderConfigError):
                reminder_service.compute_send_at(appt)


class EligibilityTest(ReminderServiceTestCase):
    def test_normal_future_appointment_is_eligible(self):
        appt = make_appointment(date="2026-12-28", time="10:00")
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self.assertTrue(reminder_service.is_eligible_for_reminder(appt, now=now, path=self.reminders_file))

    def test_exactly_24h_boundary_is_not_eligible(self):
        appt = make_appointment(date="2026-12-28", time="10:00")
        send_at = reminder_service.compute_send_at(appt)
        self.assertFalse(
            reminder_service.is_eligible_for_reminder(appt, now=send_at, path=self.reminders_file)
        )

    def test_less_than_24h_away_is_not_eligible(self):
        appt = make_appointment(date="2026-12-28", time="10:00")
        # sendAt is 2026-12-27T10:00:00+00:00 (winter, no DST); one hour
        # after that is 23h before the appointment itself.
        now = datetime(2026, 12, 27, 11, 0, tzinfo=timezone.utc)
        self.assertFalse(
            reminder_service.is_eligible_for_reminder(appt, now=now, path=self.reminders_file)
        )

    def test_past_appointment_is_not_eligible(self):
        # Same underlying condition as "less than 24h away" (see
        # REMINDER_NOTES.md) - not a separate rule, exercised here with
        # its own explicit test for clarity.
        appt = make_appointment(date="2026-01-01", time="10:00")
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self.assertFalse(
            reminder_service.is_eligible_for_reminder(appt, now=now, path=self.reminders_file)
        )

    def test_cancelled_appointment_is_not_eligible(self):
        appt = make_appointment(status="cancelled")
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertFalse(
            reminder_service.is_eligible_for_reminder(appt, now=now, path=self.reminders_file)
        )

    def test_missing_id_is_not_eligible(self):
        appt = make_appointment()
        del appt["id"]
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.assertFalse(
            reminder_service.is_eligible_for_reminder(appt, now=now, path=self.reminders_file)
        )

    def test_provider_id_absent_does_not_block_eligibility(self):
        appt = make_appointment()
        del appt["providerId"]
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self.assertTrue(
            reminder_service.is_eligible_for_reminder(appt, now=now, path=self.reminders_file)
        )

    def test_duration_minutes_is_never_consulted(self):
        appt = make_appointment(durationMinutes=999)
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self.assertTrue(
            reminder_service.is_eligible_for_reminder(appt, now=now, path=self.reminders_file)
        )


class CreateReminderTest(ReminderServiceTestCase):
    def test_creates_pending_reminder_for_eligible_appointment(self):
        appt = make_appointment(date="2026-12-28", time="10:00")
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        reminder = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)

        self.assertIsNotNone(reminder)
        self.assertEqual(reminder["appointmentId"], "appt-1")
        self.assertEqual(reminder["type"], "24h_before")
        self.assertEqual(reminder["status"], "pending")
        self.assertIsNone(reminder["sentAt"])
        self.assertIsNone(reminder["failureReason"])
        self.assertEqual(reminder["sendAt"], "2026-12-27T10:00:00+00:00")

        saved = self._read_reminders()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["id"], reminder["id"])

    def test_duplicate_pending_creation_is_a_no_op(self):
        appt = make_appointment()
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        first = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)
        second = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        saved = self._read_reminders()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["id"], first["id"])

    def test_ineligible_appointment_creates_nothing(self):
        appt = make_appointment(status="cancelled")
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        result = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)
        self.assertIsNone(result)
        self.assertFalse(os.path.exists(self.reminders_file))

    def _seed_one_terminal_reminder(self, appt, now, status):
        first = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)
        saved = self._read_reminders()
        saved[0]["status"] = status
        if status == "sent":
            saved[0]["sentAt"] = now.isoformat()
        with open(self.reminders_file, 'w') as f:
            json.dump(saved, f)
        return first

    def test_sent_reminder_does_not_block_new_creation(self):
        appt = make_appointment()
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        first = self._seed_one_terminal_reminder(appt, now, "sent")

        second = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)
        self.assertIsNotNone(second)
        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(len(self._read_reminders()), 2)

    def test_failed_reminder_does_not_block_new_creation(self):
        appt = make_appointment()
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        first = self._seed_one_terminal_reminder(appt, now, "failed")

        second = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)
        self.assertIsNotNone(second)
        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(len(self._read_reminders()), 2)

    def test_cancelled_reminder_does_not_block_new_creation(self):
        appt = make_appointment()
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        first = self._seed_one_terminal_reminder(appt, now, "cancelled")

        second = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)
        self.assertIsNotNone(second)
        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(len(self._read_reminders()), 2)

    def test_missing_clinic_timezone_raises_during_creation(self):
        appt = make_appointment()
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(reminder_config.ReminderConfigError):
                reminder_service.create_reminder(appt, now=now, path=self.reminders_file)
        self.assertFalse(os.path.exists(self.reminders_file))


class CancelPendingReminderTest(ReminderServiceTestCase):
    def test_transitions_pending_to_cancelled_without_deleting(self):
        appt = make_appointment()
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        created = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)

        cancelled_ids = reminder_service.cancel_pending_reminder(appt["id"], path=self.reminders_file)
        self.assertEqual(cancelled_ids, [created["id"]])

        saved = self._read_reminders()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["status"], "cancelled")

    def test_no_pending_reminder_is_a_safe_no_op(self):
        result = reminder_service.cancel_pending_reminder("does-not-exist", path=self.reminders_file)
        self.assertEqual(result, [])

    def test_missing_appointment_id_is_a_safe_no_op(self):
        result = reminder_service.cancel_pending_reminder(None, path=self.reminders_file)
        self.assertEqual(result, [])


class RescheduleScenarioTest(ReminderServiceTestCase):
    """Composes cancel_pending_reminder + create_reminder exactly the way
    chatbot_logic._reschedule_reminders does, at the reminder_service
    level (see ReminderIntegrationTestCase below for the same scenarios
    exercised through the real webhook).
    """

    def test_reschedule_while_pending_cancels_old_and_creates_new(self):
        appt = make_appointment(date="2026-12-28", time="10:00")
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        old = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)

        appt["date"] = "2026-12-30"
        reminder_service.cancel_pending_reminder(appt["id"], path=self.reminders_file)
        new = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)

        saved = self._read_reminders()
        self.assertEqual(len(saved), 2)
        old_after = next(r for r in saved if r["id"] == old["id"])
        self.assertEqual(old_after["status"], "cancelled")
        self.assertEqual(new["status"], "pending")
        self.assertNotEqual(old["sendAt"], new["sendAt"])

    def test_reschedule_after_sent_preserves_history_and_creates_new(self):
        # The exact scenario from the approved design revision: Appointment
        # A, 24h reminder created, SENT, then rescheduled.
        appt = make_appointment(date="2026-12-28", time="10:00")
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        original = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)
        saved = self._read_reminders()
        saved[0]["status"] = "sent"
        saved[0]["sentAt"] = now.isoformat()
        with open(self.reminders_file, 'w') as f:
            json.dump(saved, f)

        appt["date"] = "2026-12-30"
        cancelled = reminder_service.cancel_pending_reminder(appt["id"], path=self.reminders_file)
        self.assertEqual(cancelled, [])  # nothing pending to cancel - already sent
        new = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)
        self.assertIsNotNone(new)

        saved_after = self._read_reminders()
        self.assertEqual(len(saved_after), 2)
        original_after = next(r for r in saved_after if r["id"] == original["id"])
        self.assertEqual(original_after["status"], "sent")  # untouched, preserved
        self.assertEqual(new["status"], "pending")


class DueReminderTest(ReminderServiceTestCase):
    def test_due_at_exact_send_at_is_inclusive(self):
        appt = make_appointment()
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        created = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)

        exactly_send_at = datetime.fromisoformat(created["sendAt"])
        due = reminder_service.get_due_reminders(now=exactly_send_at, path=self.reminders_file)
        self.assertEqual([r["id"] for r in due], [created["id"]])

    def test_not_yet_due_is_excluded(self):
        appt = make_appointment()
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        created = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)

        one_minute_early = datetime.fromisoformat(created["sendAt"]) - timedelta(minutes=1)
        due = reminder_service.get_due_reminders(now=one_minute_early, path=self.reminders_file)
        self.assertEqual(due, [])

    def test_non_pending_reminders_are_never_due(self):
        appt = make_appointment()
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        created = reminder_service.create_reminder(appt, now=now, path=self.reminders_file)
        reminder_service.cancel_pending_reminder(appt["id"], path=self.reminders_file)

        well_after = datetime.fromisoformat(created["sendAt"]) + timedelta(days=1)
        due = reminder_service.get_due_reminders(now=well_after, path=self.reminders_file)
        self.assertEqual(due, [])


def make_reminder(**overrides):
    reminder = {
        "id": "r1",
        "appointmentId": "a1",
        "type": "24h_before",
        "sendAt": datetime(2026, 12, 1, tzinfo=timezone.utc).isoformat(),
        "status": "pending",
        "createdAt": datetime(2026, 11, 1, tzinfo=timezone.utc).isoformat(),
        "sentAt": None,
        "failureReason": None,
    }
    reminder.update(overrides)
    return reminder


class ProcessDueRemindersTest(ReminderServiceTestCase):
    """Tests for process_due_reminders() (Phase 6.2-B). CLINIC_TIMEZONE is
    still set by the base class's setUp, but every test here deliberately
    never relies on it - send/failed/cancelled outcomes and due-detection
    are fully determined by stored (already-UTC) sendAt values and the
    injected `now`, proving due processing has no timezone dependency.
    """

    def setUp(self):
        super().setUp()
        self.appointments_file = os.path.join(self.tmp_dir.name, 'appointments.json')

    def _write_appointments(self, appointments):
        with open(self.appointments_file, 'w') as f:
            json.dump(appointments, f)

    def _write_reminders(self, reminders):
        with open(self.reminders_file, 'w') as f:
            json.dump(reminders, f)

    def _active_appointment(self, appointment_id="a1"):
        return {
            "id": appointment_id, "name": "Test Patient", "providerId": "dr-patel",
            "date": "2026-12-28", "time": "10:00",
        }

    def test_exact_due_boundary_is_processed(self):
        send_at = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self._write_reminders([make_reminder(sendAt=send_at.isoformat())])
        self._write_appointments([self._active_appointment()])

        processed = reminder_service.process_due_reminders(
            lambda r, a: True, now=send_at, path=self.reminders_file, appointments_path=self.appointments_file
        )
        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0]["status"], "sent")

    def test_one_second_before_boundary_is_not_processed(self):
        send_at = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self._write_reminders([make_reminder(sendAt=send_at.isoformat())])
        self._write_appointments([self._active_appointment()])

        one_second_early = send_at - timedelta(seconds=1)
        processed = reminder_service.process_due_reminders(
            lambda r, a: True, now=one_second_early,
            path=self.reminders_file, appointments_path=self.appointments_file,
        )
        self.assertEqual(processed, [])
        saved = self._read_reminders()
        self.assertEqual(saved[0]["status"], "pending")

    def test_successful_send_transitions_to_sent_with_send_at_timestamp(self):
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self._write_reminders([make_reminder(sendAt=now.isoformat())])
        self._write_appointments([self._active_appointment()])

        processed = reminder_service.process_due_reminders(
            lambda r, a: True, now=now, path=self.reminders_file, appointments_path=self.appointments_file
        )
        self.assertEqual(processed[0]["status"], "sent")
        self.assertEqual(processed[0]["sentAt"], now.isoformat())
        self.assertIsNone(processed[0]["failureReason"])

    def test_failed_send_transitions_to_failed_with_send_failed_reason(self):
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self._write_reminders([make_reminder(sendAt=now.isoformat())])
        self._write_appointments([self._active_appointment()])

        processed = reminder_service.process_due_reminders(
            lambda r, a: False, now=now, path=self.reminders_file, appointments_path=self.appointments_file
        )
        self.assertEqual(processed[0]["status"], "failed")
        self.assertEqual(processed[0]["failureReason"], reminder_service.REMINDER_FAILURE_SEND_FAILED)
        self.assertIsNone(processed[0]["sentAt"])

    def test_missing_appointment_transitions_to_failed_with_not_found_reason(self):
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self._write_reminders([make_reminder(sendAt=now.isoformat())])
        self._write_appointments([])  # no matching appointment record at all

        processed = reminder_service.process_due_reminders(
            lambda r, a: True, now=now, path=self.reminders_file, appointments_path=self.appointments_file
        )
        self.assertEqual(processed[0]["status"], "failed")
        self.assertEqual(processed[0]["failureReason"], reminder_service.REMINDER_FAILURE_APPOINTMENT_NOT_FOUND)

    def test_cancelled_appointment_transitions_reminder_to_cancelled(self):
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self._write_reminders([make_reminder(sendAt=now.isoformat())])
        appt = self._active_appointment()
        appt["status"] = "cancelled"
        self._write_appointments([appt])

        processed = reminder_service.process_due_reminders(
            lambda r, a: True, now=now, path=self.reminders_file, appointments_path=self.appointments_file
        )
        self.assertEqual(processed[0]["status"], "cancelled")
        self.assertIsNone(processed[0]["failureReason"])
        self.assertIsNone(processed[0]["sentAt"])

    def test_repeated_processing_is_idempotent(self):
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self._write_reminders([make_reminder(sendAt=now.isoformat())])
        self._write_appointments([self._active_appointment()])

        send = Mock(return_value=True)
        first = reminder_service.process_due_reminders(
            send, now=now, path=self.reminders_file, appointments_path=self.appointments_file
        )
        second = reminder_service.process_due_reminders(
            send, now=now, path=self.reminders_file, appointments_path=self.appointments_file
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(send.call_count, 1)

    def test_terminal_reminders_are_ignored(self):
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self._write_reminders([
            make_reminder(id="r-sent", status="sent", sentAt=now.isoformat(), sendAt=now.isoformat()),
            make_reminder(id="r-failed", status="failed", failureReason="send_failed", sendAt=now.isoformat()),
            make_reminder(id="r-cancelled", status="cancelled", sendAt=now.isoformat()),
        ])
        self._write_appointments([self._active_appointment()])

        processed = reminder_service.process_due_reminders(
            lambda r, a: True, now=now, path=self.reminders_file, appointments_path=self.appointments_file
        )
        self.assertEqual(processed, [])

    def test_malformed_reminder_raises_and_processes_nothing(self):
        self._write_reminders([{"id": "bad", "appointmentId": "a1", "type": "24h_before"}])
        with self.assertRaises(reminder_service.ReminderDataError):
            reminder_service.process_due_reminders(
                lambda r, a: True, path=self.reminders_file, appointments_path=self.appointments_file
            )

    def test_multiple_reminders_receive_independent_outcomes(self):
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self._write_reminders([
            make_reminder(id="r-ok", appointmentId="a-ok", sendAt=now.isoformat()),
            make_reminder(id="r-fail", appointmentId="a-fail", sendAt=now.isoformat()),
            make_reminder(id="r-missing", appointmentId="a-missing", sendAt=now.isoformat()),
        ])
        self._write_appointments([
            self._active_appointment("a-ok"),
            self._active_appointment("a-fail"),
            # "a-missing" is intentionally absent.
        ])

        def send(reminder, appointment):
            return reminder["id"] == "r-ok"

        processed = reminder_service.process_due_reminders(
            send, now=now, path=self.reminders_file, appointments_path=self.appointments_file
        )
        outcomes = {r["id"]: r["status"] for r in processed}
        self.assertEqual(outcomes, {"r-ok": "sent", "r-fail": "failed", "r-missing": "failed"})
        reasons = {r["id"]: r["failureReason"] for r in processed}
        self.assertEqual(reasons["r-fail"], reminder_service.REMINDER_FAILURE_SEND_FAILED)
        self.assertEqual(reasons["r-missing"], reminder_service.REMINDER_FAILURE_APPOINTMENT_NOT_FOUND)

    def test_sender_exception_is_isolated_to_that_reminder_and_batch_continues(self):
        # Phase 6.2-C: a future real provider can raise (a network
        # timeout, a malformed response, etc.) rather than cleanly
        # returning False. This must be caught and treated as an ordinary
        # delivery failure for exactly that one reminder - not abort the
        # whole batch - and no exception should ever escape
        # process_due_reminders() itself.
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self._write_reminders([
            make_reminder(id="r-raises", appointmentId="a-raises", sendAt=now.isoformat()),
            make_reminder(id="r-ok", appointmentId="a-ok", sendAt=now.isoformat()),
        ])
        self._write_appointments([
            self._active_appointment("a-raises"),
            self._active_appointment("a-ok"),
        ])

        def send(reminder, appointment):
            if reminder["id"] == "r-raises":
                raise RuntimeError("simulated provider failure - network timeout")
            return True

        # No exception escapes the call itself.
        processed = reminder_service.process_due_reminders(
            send, now=now, path=self.reminders_file, appointments_path=self.appointments_file
        )

        outcomes = {r["id"]: r for r in processed}

        # 1. Sender exception -> failed/send_failed.
        self.assertEqual(outcomes["r-raises"]["status"], "failed")
        self.assertEqual(outcomes["r-raises"]["failureReason"], reminder_service.REMINDER_FAILURE_SEND_FAILED)
        self.assertIsNone(outcomes["r-raises"]["sentAt"])

        # 2. The other due reminder still processes successfully.
        # 3. Its sentAt comes from the injected `now`, not real wall-clock time.
        self.assertEqual(outcomes["r-ok"]["status"], "sent")
        self.assertEqual(outcomes["r-ok"]["sentAt"], now.isoformat())
        self.assertIsNone(outcomes["r-ok"]["failureReason"])

        # Both outcomes are actually persisted, not just returned in memory.
        saved = {r["id"]: r for r in self._read_reminders()}
        self.assertEqual(saved["r-raises"]["status"], "failed")
        self.assertEqual(saved["r-ok"]["status"], "sent")

    def test_non_due_reminders_remain_unchanged(self):
        now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        future_send_at = now + timedelta(days=1)
        self._write_reminders([make_reminder(sendAt=future_send_at.isoformat())])
        self._write_appointments([self._active_appointment()])

        processed = reminder_service.process_due_reminders(
            lambda r, a: True, now=now, path=self.reminders_file, appointments_path=self.appointments_file
        )
        self.assertEqual(processed, [])
        saved = self._read_reminders()
        self.assertEqual(saved[0]["status"], "pending")

    def test_no_real_wall_clock_dependency(self):
        # A `now` far from real wall-clock time, with a matching sendAt,
        # must still be processed correctly - proving the function never
        # falls back to a real datetime.now() when `now` is supplied.
        long_ago = datetime(2000, 1, 1, tzinfo=timezone.utc)
        self._write_reminders([make_reminder(sendAt=long_ago.isoformat())])
        self._write_appointments([self._active_appointment()])

        processed = reminder_service.process_due_reminders(
            lambda r, a: True, now=long_ago, path=self.reminders_file, appointments_path=self.appointments_file
        )
        self.assertEqual(len(processed), 1)
        self.assertEqual(processed[0]["sentAt"], long_ago.isoformat())


class MalformedReminderRecordTest(ReminderServiceTestCase):
    def _write_raw(self, records):
        with open(self.reminders_file, 'w') as f:
            json.dump(records, f)

    def test_unknown_status_fails_loudly(self):
        self._write_raw([{
            "id": "r1", "appointmentId": "appt-1", "type": "24h_before",
            "sendAt": "2026-12-27T10:00:00+00:00", "status": "bogus",
            "createdAt": "2026-12-01T00:00:00+00:00", "sentAt": None, "failureReason": None,
        }])
        with self.assertRaises(reminder_service.ReminderDataError):
            reminder_service.find_pending_reminder("appt-1", "24h_before", path=self.reminders_file)
        with self.assertRaises(reminder_service.ReminderDataError):
            reminder_service.get_due_reminders(path=self.reminders_file)

    def test_missing_required_field_fails_loudly(self):
        self._write_raw([{"id": "r1", "appointmentId": "appt-1", "type": "24h_before"}])
        with self.assertRaises(reminder_service.ReminderDataError):
            reminder_service.find_pending_reminder("appt-1", "24h_before", path=self.reminders_file)

    def test_invalid_send_at_fails_loudly_on_due_check(self):
        self._write_raw([{
            "id": "r1", "appointmentId": "appt-1", "type": "24h_before",
            "sendAt": "not-a-date", "status": "pending",
            "createdAt": "2026-12-01T00:00:00+00:00", "sentAt": None, "failureReason": None,
        }])
        with self.assertRaises(reminder_service.ReminderDataError):
            reminder_service.get_due_reminders(path=self.reminders_file)


class ReminderIntegrationTestCase(unittest.TestCase):
    """Full webhook-level tests proving chatbot_logic.py's three reminder
    integration hooks (_schedule_reminder_for_booking / _reschedule_reminders /
    _cancel_reminders) are actually wired up correctly - not just that
    reminder_service.py's own functions work in isolation. Self-contained
    (no cross-class inheritance), matching this project's established
    pattern for avoiding unittest's inherited-test-duplication risk.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

        self.appointments_file = os.path.join(self.tmp_dir.name, 'appointments.json')
        self.pending_file = os.path.join(self.tmp_dir.name, 'pending_appointments.json')
        self.pending_cancellation_file = os.path.join(self.tmp_dir.name, 'pending_cancellation.json')
        self.pending_update_file = os.path.join(self.tmp_dir.name, 'pending_update.json')
        self.reminders_file = os.path.join(self.tmp_dir.name, 'reminders.json')

        patchers = [
            patch.object(chatbot_logic, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(chatbot_logic, 'PENDING_FILE', self.pending_file),
            patch.object(chatbot_logic, 'PENDING_CANCELLATION_FILE', self.pending_cancellation_file),
            patch.object(chatbot_logic, 'PENDING_UPDATE_FILE', self.pending_update_file),
            patch.object(availability_service, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(reminder_service, 'REMINDERS_FILE', self.reminders_file),
            patch.dict('os.environ', {'CLINIC_TIMEZONE': 'Europe/London'}, clear=False),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.client = app.test_client()

    def post_webhook(self, intent, parameters=None):
        body = {"queryResult": {"intent": {"displayName": intent}, "parameters": parameters or {}}}
        return self.client.post('/webhook/webhook', json=body)

    def _book_and_confirm(self, name="Test Patient", provider_id="dr-patel", date="2026-12-28", time="10:00"):
        self.post_webhook(
            "Book Appointment", {"name": name, "providerId": provider_id, "date": date, "time": time}
        )
        booked = self.post_webhook("YesIntent").get_json()
        return booked["messages"][0]["content"]["appointment"]

    def _read_reminders(self):
        if not os.path.exists(self.reminders_file):
            return []
        with open(self.reminders_file, 'r') as f:
            return json.load(f)

    def _read_appointments(self):
        with open(self.appointments_file, 'r') as f:
            return json.load(f)

    def test_eligible_booking_creates_exactly_one_pending_24h_before_reminder(self):
        # Phase 6.2-H: booking itself now creates a reminder for an
        # eligible (active, far-enough-future) appointment - reversing
        # the old test_booking_alone_never_creates_a_reminder assumption,
        # which is no longer this project's intended behavior.
        appointment = self._book_and_confirm(date="2026-12-28", time="10:00")

        self.assertTrue(appointment.get("id"))
        reminders = self._read_reminders()
        self.assertEqual(len(reminders), 1)
        reminder = reminders[0]
        self.assertEqual(reminder["status"], "pending")
        self.assertEqual(reminder["type"], "24h_before")
        self.assertEqual(reminder["appointmentId"], appointment["id"])
        expected_send_at = reminder_service.compute_send_at(appointment)
        self.assertEqual(datetime.fromisoformat(reminder["sendAt"]), expected_send_at)

    def test_ineligible_booking_less_than_24h_away_creates_no_reminder(self):
        # reminder_service treats "less than 24h away" and "already past"
        # as the SAME eligibility condition (sendAt <= now - see
        # REMINDER_NOTES.md's "Two distinct inequalities" section) - a
        # fixed past date is used here rather than a live wall-clock-
        # relative time, since dr-patel's fixed weekly availability
        # (Monday/Wednesday only, backend/provider_availability.json)
        # makes constructing a real, bookable "<24h from whenever this
        # suite happens to run" slot unreliable (a test run on a Friday
        # afternoon through Sunday would find no such slot at all).
        # 2020-01-01 is a Wednesday - a valid, always-bookable slot day -
        # and is unambiguously both "less than 24h away" and "in the
        # past" by the time this test runs.
        appointment = self._book_and_confirm(date="2020-01-01", time="10:00")

        self.assertTrue(appointment.get("id"))
        self.assertEqual(self._read_reminders(), [])

    def test_missing_clinic_timezone_does_not_break_booking(self):
        with patch.dict('os.environ', {}, clear=True):
            self.post_webhook(
                "Book Appointment",
                {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
            )
            confirmed = self.post_webhook("YesIntent").get_json()

        self.assertTrue(confirmed["success"])
        message = confirmed["messages"][0]
        self.assertEqual(message["type"], "booking_confirmation")
        # Response shape unchanged by Phase 6.2-H: still exactly text +
        # appointment, no reminder-related text/field/metadata added.
        self.assertEqual(set(message["content"].keys()), {"text", "appointment"})
        self.assertIn("has been booked", message["content"]["text"])

        appointment = message["content"]["appointment"]
        saved_appointments = self._read_appointments()
        self.assertEqual(len(saved_appointments), 1)
        self.assertEqual(saved_appointments[0]["id"], appointment["id"])

        # Pending-booking cleanup still occurred despite the reminder-
        # scheduling failure (missing CLINIC_TIMEZONE).
        self.assertFalse(os.path.exists(self.pending_file))

        # Reminder creation failed silently (ReminderConfigError, caught
        # and logged by _schedule_reminder_for_booking) - no reminder was
        # created, but nothing above was affected by that failure.
        self.assertEqual(self._read_reminders(), [])

    def test_cancellation_with_nothing_pending_does_not_error(self):
        # A past-dated appointment is not reminder-eligible (see
        # reminder_service.is_eligible_for_reminder), so booking one
        # leaves nothing pending - exercising cancel_pending_reminder's
        # own documented safe no-op for that case.
        appointment = self._book_and_confirm(date="2020-01-01", time="10:00")
        self.assertEqual(self._read_reminders(), [])

        self.post_webhook("Cancel Appointment", {"id": appointment["id"]})
        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been cancelled", confirmed["messages"][0]["content"]["text"])
        self.assertEqual(self._read_reminders(), [])

    def test_cancellation_transitions_an_existing_pending_reminder(self):
        appointment = self._book_and_confirm(date="2026-12-28", time="10:00")
        # Booking itself already created the pending reminder (Phase
        # 6.2-H) - a further manual create_reminder() call is unnecessary
        # (and would itself be a silent no-op, per create_reminder()'s own
        # idempotency rule: at most one pending reminder per
        # (appointmentId, type)).
        self.assertEqual(len(self._read_reminders()), 1)

        self.post_webhook("Cancel Appointment", {"id": appointment["id"]})
        self.post_webhook("YesIntent")

        saved = self._read_reminders()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["status"], "cancelled")

    def test_reschedule_cancels_old_pending_and_creates_new(self):
        appointment = self._book_and_confirm(date="2026-12-28", time="10:00")
        # Booking itself already created the pending reminder (Phase 6.2-H).
        before = self._read_reminders()
        self.assertEqual(len(before), 1)
        created_id = before[0]["id"]

        self.post_webhook("Update Appointment", {"id": appointment["id"], "date": "2026-12-30"})
        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been updated", confirmed["messages"][0]["content"]["text"])

        saved = self._read_reminders()
        self.assertEqual(len(saved), 2)
        old = next(r for r in saved if r["id"] == created_id)
        self.assertEqual(old["status"], "cancelled")
        new = next(r for r in saved if r["id"] != created_id)
        self.assertEqual(new["status"], "pending")
        self.assertNotEqual(new["sendAt"], old["sendAt"])

    def test_reschedule_after_sent_creates_a_new_reminder_and_preserves_history(self):
        appointment = self._book_and_confirm(date="2026-12-28", time="10:00")
        # Booking itself already created the pending reminder (Phase 6.2-H).
        saved = self._read_reminders()
        self.assertEqual(len(saved), 1)
        created_id = saved[0]["id"]
        saved[0]["status"] = "sent"
        saved[0]["sentAt"] = "2026-12-27T10:00:00+00:00"
        with open(self.reminders_file, 'w') as f:
            json.dump(saved, f)

        self.post_webhook("Update Appointment", {"id": appointment["id"], "date": "2026-12-30"})
        self.post_webhook("YesIntent")

        saved_after = self._read_reminders()
        self.assertEqual(len(saved_after), 2)
        original_after = next(r for r in saved_after if r["id"] == created_id)
        self.assertEqual(original_after["status"], "sent")
        new = next(r for r in saved_after if r["id"] != created_id)
        self.assertEqual(new["status"], "pending")

    def test_missing_clinic_timezone_does_not_break_cancellation(self):
        appointment = self._book_and_confirm()
        with patch.dict('os.environ', {}, clear=True):
            self.post_webhook("Cancel Appointment", {"id": appointment["id"]})
            confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been cancelled", confirmed["messages"][0]["content"]["text"])
        saved = self._read_appointments()
        self.assertEqual(saved[0]["status"], "cancelled")

    def test_missing_clinic_timezone_does_not_break_update(self):
        appointment = self._book_and_confirm()
        # Booking itself already created one pending reminder (Phase 6.2-H),
        # while CLINIC_TIMEZONE was still configured.
        self.assertEqual(len(self._read_reminders()), 1)

        with patch.dict('os.environ', {}, clear=True):
            self.post_webhook("Update Appointment", {"id": appointment["id"], "date": "2026-12-30"})
            confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been updated", confirmed["messages"][0]["content"]["text"])
        # The old pending reminder was still cancelled (cancellation needs
        # no timezone), but a new one could not be created without a
        # configured CLINIC_TIMEZONE - this must be silent (a logged
        # warning, not a user-visible error), leaving exactly the one,
        # now-cancelled record behind rather than a corrupt/partial
        # reminders.json or a wrongly-created second one.
        saved = self._read_reminders()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["status"], "cancelled")


if __name__ == '__main__':
    unittest.main()
