"""Tests for backend/run_due_reminders.py (Phase 6.2-D/E).

Most tests call main(argv) directly, in-process - never a real
subprocess - and mock/patch backend.run_due_reminders.reminder_service
so nothing here ever touches a real or even a temp reminders.json/
appointments.json. This module owns no domain logic of its own (see its
own docstring), so most of these tests are only about the CLI boundary
itself: argument parsing, dispatch, exit codes, and logged content -
never reminder eligibility/state-transition behavior, which is already
fully covered by backend/tests/test_reminder_service.py.

Phase 6.2-E adds one exception to that "always mock reminder_service"
rule: MockProviderEndToEndTest below deliberately does NOT mock
reminder_service.process_due_reminders() - it redirects
reminder_service.REMINDERS_FILE/APPOINTMENTS_FILE to a temp directory
(the same isolation pattern backend/tests/test_reminder_service.py's own
ReminderIntegrationTestCase already uses) and lets the REAL processor run
against backend.mock_notification_provider, to prove the whole pipeline
- CLI -> real process_due_reminders() -> mock send() -> persisted
reminders.json - actually works end-to-end, not just that the CLI calls
the right mocked function.
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from backend import mock_notification_provider, reminder_service, run_due_reminders


def make_reminder(reminder_id="r1", appointment_id="a1"):
    # A representative, fully-formed reminder record - used only to prove
    # a *count* is reported; no test here ever asserts on its id/content
    # appearing anywhere in CLI output or logs.
    return {
        "id": reminder_id,
        "appointmentId": appointment_id,
        "type": "24h_before",
        "sendAt": "2026-12-01T00:00:00+00:00",
        "status": "pending",
        "createdAt": "2026-11-01T00:00:00+00:00",
        "sentAt": None,
        "failureReason": None,
    }


class DryRunTest(unittest.TestCase):
    @patch.object(run_due_reminders.reminder_service, "process_due_reminders")
    @patch.object(run_due_reminders.reminder_service, "get_due_reminders")
    def test_dry_run_with_zero_due_reminders_exits_zero(self, mock_get_due, mock_process):
        mock_get_due.return_value = []

        exit_code = run_due_reminders.main(["--dry-run"])

        self.assertEqual(exit_code, 0)
        # now=None: the default when --now is omitted (see NowOverrideTest
        # below for --now's own coverage) - unchanged behavior otherwise.
        mock_get_due.assert_called_once_with(now=None)
        mock_process.assert_not_called()

    @patch.object(run_due_reminders.reminder_service, "process_due_reminders")
    @patch.object(run_due_reminders.reminder_service, "get_due_reminders")
    def test_dry_run_with_due_reminders_reports_correct_count_and_exits_zero(
        self, mock_get_due, mock_process
    ):
        mock_get_due.return_value = [make_reminder("r1"), make_reminder("r2"), make_reminder("r3")]

        with self.assertLogs(run_due_reminders.logger, level="INFO") as captured:
            exit_code = run_due_reminders.main(["--dry-run"])

        self.assertEqual(exit_code, 0)
        mock_process.assert_not_called()
        self.assertTrue(any("Due reminders: 3" in line for line in captured.output))

    @patch.object(run_due_reminders.reminder_service, "process_due_reminders")
    @patch.object(run_due_reminders.reminder_service, "get_due_reminders")
    def test_dry_run_never_invokes_a_sender(self, mock_get_due, mock_process):
        # There is no `send` parameter available to a dry run at all - the
        # only way a sender could ever be invoked is via
        # process_due_reminders(), and this proves that is never called,
        # regardless of how many reminders are due.
        mock_get_due.return_value = [make_reminder()]

        run_due_reminders.main(["--dry-run"])

        mock_process.assert_not_called()

    @patch.object(run_due_reminders.reminder_service, "get_due_reminders")
    def test_dry_run_malformed_data_exits_non_zero(self, mock_get_due):
        mock_get_due.side_effect = run_due_reminders.reminder_service.ReminderDataError("bad record")

        with self.assertLogs(run_due_reminders.logger, level="ERROR") as captured:
            exit_code = run_due_reminders.main(["--dry-run"])

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(exit_code, run_due_reminders.EXIT_MALFORMED_DATA)
        # Only the exception TYPE name may appear - never its message text
        # (which could echo a reminder id or appointment content).
        self.assertTrue(any("ReminderDataError" in line for line in captured.output))
        self.assertFalse(any("bad record" in line for line in captured.output))

    @patch.object(run_due_reminders.reminder_service, "get_due_reminders")
    def test_dry_run_unexpected_runtime_failure_exits_non_zero_and_logs_safely(self, mock_get_due):
        mock_get_due.side_effect = RuntimeError("some internal detail that must never be logged")

        with self.assertLogs(run_due_reminders.logger, level="ERROR") as captured:
            exit_code = run_due_reminders.main(["--dry-run"])

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(exit_code, run_due_reminders.EXIT_RUNTIME_FAILURE)
        self.assertTrue(any("RuntimeError" in line for line in captured.output))
        self.assertFalse(
            any("some internal detail that must never be logged" in line for line in captured.output)
        )


class MutatingModeTest(unittest.TestCase):
    """NOTIFICATION_PROVIDER is explicitly pinned to "" (unset-equivalent,
    see ProviderSelectionTest below for the full selection-logic coverage)
    in every test here, so these tests are deterministic regardless of
    whatever NOTIFICATION_PROVIDER happens to be set to in the real shell
    environment running the test suite.
    """

    @patch.object(run_due_reminders.reminder_service, "process_due_reminders")
    @patch.object(run_due_reminders.reminder_service, "get_due_reminders")
    def test_normal_invocation_with_no_sender_exits_non_zero_and_mutates_nothing(
        self, mock_get_due, mock_process
    ):
        with patch.dict("os.environ", {"NOTIFICATION_PROVIDER": ""}):
            exit_code = run_due_reminders.main([])

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(exit_code, run_due_reminders.EXIT_NO_SENDER_CONFIGURED)
        mock_process.assert_not_called()
        # Nothing that could mutate reminder state is even consulted -
        # get_due_reminders() is never called by the mutating path either
        # (see _run_mutating's own docstring: it refuses immediately).
        mock_get_due.assert_not_called()

    @patch.object(run_due_reminders.reminder_service, "process_due_reminders")
    def test_normal_invocation_logs_safely(self, mock_process):
        with patch.dict("os.environ", {"NOTIFICATION_PROVIDER": ""}):
            with self.assertLogs(run_due_reminders.logger, level="ERROR") as captured:
                run_due_reminders.main([])

        self.assertTrue(any("no notification provider" in line.lower() for line in captured.output))
        mock_process.assert_not_called()


class ArgvHandlingTest(unittest.TestCase):
    @patch.object(run_due_reminders.reminder_service, "get_due_reminders", return_value=[])
    def test_argv_none_uses_normal_argparse_behavior(self, mock_get_due):
        # With argv=None and no --dry-run present in the real process
        # argv, argparse falls back to sys.argv[1:] - under the test
        # runner that is empty/irrelevant flags, so this exercises the
        # same "normal invocation, no sender" path deterministically.
        # NOTIFICATION_PROVIDER is pinned to "" so this is deterministic
        # regardless of the real shell environment running the suite.
        with patch("sys.argv", ["run_due_reminders"]), patch.dict("os.environ", {"NOTIFICATION_PROVIDER": ""}):
            exit_code = run_due_reminders.main(None)

        self.assertEqual(exit_code, run_due_reminders.EXIT_NO_SENDER_CONFIGURED)

    @patch.object(run_due_reminders.reminder_service, "get_due_reminders", return_value=[])
    def test_argv_none_with_dry_run_flag_in_sys_argv(self, mock_get_due):
        with patch("sys.argv", ["run_due_reminders", "--dry-run"]):
            exit_code = run_due_reminders.main(None)

        self.assertEqual(exit_code, 0)
        mock_get_due.assert_called_once_with(now=None)

    def test_unknown_flag_is_rejected_by_argparse(self):
        with self.assertRaises(SystemExit):
            run_due_reminders.main(["--not-a-real-flag"])


class OutputSafetyTest(unittest.TestCase):
    """Cross-cutting: proves NOTHING identifying ever appears in CLI
    output/logs, across every path this module has.
    """

    _FORBIDDEN_SUBSTRINGS = (
        "r1", "r2", "r3", "a1", "a2", "a3",  # reminder/appointment ids used in fixtures
        "24h_before", "2026-12-01", "2026-11-01",  # reminder field values
    )

    @patch.object(run_due_reminders.reminder_service, "get_due_reminders")
    def test_dry_run_output_contains_no_reminder_or_appointment_detail(self, mock_get_due):
        mock_get_due.return_value = [make_reminder("r1", "a1"), make_reminder("r2", "a2")]

        with self.assertLogs(run_due_reminders.logger, level="INFO") as captured:
            run_due_reminders.main(["--dry-run"])

        full_output = "\n".join(captured.output)
        for forbidden in self._FORBIDDEN_SUBSTRINGS:
            self.assertNotIn(forbidden, full_output)


class ProviderSelectionTest(unittest.TestCase):
    """NOTIFICATION_PROVIDER selection at the CLI boundary - still with
    reminder_service.process_due_reminders() mocked, since these tests are
    only about whether it gets CALLED (and with what), not about the real
    state-transition pipeline (that's MockProviderEndToEndTest below).
    """

    @patch.object(run_due_reminders.reminder_service, "process_due_reminders")
    def test_no_provider_configured_exits_no_sender_configured(self, mock_process):
        with patch.dict("os.environ", {"NOTIFICATION_PROVIDER": ""}):
            exit_code = run_due_reminders.main([])

        self.assertEqual(exit_code, run_due_reminders.EXIT_NO_SENDER_CONFIGURED)
        mock_process.assert_not_called()

    @patch.object(run_due_reminders.reminder_service, "process_due_reminders")
    def test_unknown_provider_value_exits_no_sender_configured_not_mock(self, mock_process):
        with patch.dict("os.environ", {"NOTIFICATION_PROVIDER": "sendgrid"}):
            exit_code = run_due_reminders.main([])

        self.assertEqual(exit_code, run_due_reminders.EXIT_NO_SENDER_CONFIGURED)
        mock_process.assert_not_called()

    @patch.object(run_due_reminders.reminder_service, "process_due_reminders", return_value=[])
    def test_notification_provider_mock_invokes_real_process_due_reminders_with_mock_send(
        self, mock_process
    ):
        with patch.dict("os.environ", {"NOTIFICATION_PROVIDER": "mock"}):
            exit_code = run_due_reminders.main([])

        self.assertEqual(exit_code, run_due_reminders.EXIT_OK)
        mock_process.assert_called_once_with(send=mock_notification_provider.send, now=None)

    @patch.object(run_due_reminders.reminder_service, "process_due_reminders")
    def test_notification_provider_mock_is_case_insensitive_and_trims_whitespace(self, mock_process):
        mock_process.return_value = []
        with patch.dict("os.environ", {"NOTIFICATION_PROVIDER": "  MOCK  "}):
            exit_code = run_due_reminders.main([])

        self.assertEqual(exit_code, run_due_reminders.EXIT_OK)
        mock_process.assert_called_once_with(send=mock_notification_provider.send, now=None)


class DryRunProviderIsolationTest(unittest.TestCase):
    """Proves --dry-run stays completely non-mutating even when a
    provider IS configured - it must never reach process_due_reminders()
    or the mock provider's own send() at all.
    """

    @patch.object(run_due_reminders.mock_notification_provider, "send")
    @patch.object(run_due_reminders.reminder_service, "process_due_reminders")
    @patch.object(run_due_reminders.reminder_service, "get_due_reminders", return_value=[])
    def test_dry_run_never_invokes_process_due_reminders_or_mock_send_when_configured(
        self, mock_get_due, mock_process, mock_send
    ):
        with patch.dict("os.environ", {"NOTIFICATION_PROVIDER": "mock"}):
            exit_code = run_due_reminders.main(["--dry-run"])

        self.assertEqual(exit_code, run_due_reminders.EXIT_OK)
        mock_get_due.assert_called_once_with(now=None)
        mock_process.assert_not_called()
        mock_send.assert_not_called()


def make_due_reminder(reminder_id, appointment_id="a1"):
    """A `pending` reminder whose sendAt is far in the past - always due,
    regardless of the real wall-clock time the test happens to run at.
    """
    return {
        "id": reminder_id,
        "appointmentId": appointment_id,
        "type": "24h_before",
        "sendAt": "2020-01-01T00:00:00+00:00",
        "status": "pending",
        "createdAt": "2019-12-01T00:00:00+00:00",
        "sentAt": None,
        "failureReason": None,
    }


def make_active_appointment(appointment_id="a1"):
    return {
        "id": appointment_id,
        "name": "Test Patient",
        "date": "2099-01-01",
        "time": "10:00",
        "providerId": "p1",
        "durationMinutes": 30,
    }


class MockProviderEndToEndTest(unittest.TestCase):
    """Exercises the REAL pipeline: main() -> the REAL
    reminder_service.process_due_reminders() -> mock_notification_provider.send()
    -> persisted (temp-file) reminders.json. process_due_reminders() is
    never mocked in this class - only reminder_service.REMINDERS_FILE/
    APPOINTMENTS_FILE are redirected to a temp directory, matching the
    isolation pattern backend/tests/test_reminder_service.py's own
    ReminderIntegrationTestCase already uses. The real repository's
    backend/reminders.json and backend/appointments.json are never read
    or written by any test in this class (see
    test_real_repository_data_files_are_not_modified below, which proves
    it directly rather than assuming it).
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.reminders_file = os.path.join(self.tmp_dir.name, "reminders.json")
        self.appointments_file = os.path.join(self.tmp_dir.name, "appointments.json")

        patchers = [
            patch.object(reminder_service, "REMINDERS_FILE", self.reminders_file),
            patch.object(reminder_service, "APPOINTMENTS_FILE", self.appointments_file),
            patch.dict("os.environ", {"NOTIFICATION_PROVIDER": "mock"}),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f)

    def _read(self, path):
        with open(path) as f:
            return json.load(f)

    def test_mock_success_marks_reminder_sent_with_sent_at(self):
        self._write(self.appointments_file, [make_active_appointment("a1")])
        self._write(self.reminders_file, [make_due_reminder("r-ok", "a1")])

        exit_code = run_due_reminders.main([])

        self.assertEqual(exit_code, run_due_reminders.EXIT_OK)
        reminders = self._read(self.reminders_file)
        self.assertEqual(reminders[0]["status"], "sent")
        self.assertIsNotNone(reminders[0]["sentAt"])
        self.assertIsNone(reminders[0]["failureReason"])

    def test_mock_false_marks_reminder_failed_send_failed(self):
        failing_id = f"r-fail{mock_notification_provider.MOCK_FAILURE_MARKER}"
        self._write(self.appointments_file, [make_active_appointment("a1")])
        self._write(self.reminders_file, [make_due_reminder(failing_id, "a1")])

        exit_code = run_due_reminders.main([])

        self.assertEqual(exit_code, run_due_reminders.EXIT_OK)
        reminders = self._read(self.reminders_file)
        self.assertEqual(reminders[0]["status"], "failed")
        self.assertEqual(reminders[0]["failureReason"], "send_failed")

    def test_mock_exception_marks_reminder_failed_send_failed_without_crashing(self):
        erroring_id = f"r-err{mock_notification_provider.MOCK_ERROR_MARKER}"
        self._write(self.appointments_file, [make_active_appointment("a1")])
        self._write(self.reminders_file, [make_due_reminder(erroring_id, "a1")])

        exit_code = run_due_reminders.main([])

        self.assertEqual(exit_code, run_due_reminders.EXIT_OK)
        reminders = self._read(self.reminders_file)
        self.assertEqual(reminders[0]["status"], "failed")
        self.assertEqual(reminders[0]["failureReason"], "send_failed")

    def test_multiple_reminders_processed_independently(self):
        ok_id = "r-ok"
        fail_id = f"r-fail{mock_notification_provider.MOCK_FAILURE_MARKER}"
        error_id = f"r-err{mock_notification_provider.MOCK_ERROR_MARKER}"
        self._write(self.appointments_file, [make_active_appointment("a1")])
        self._write(
            self.reminders_file,
            [
                make_due_reminder(ok_id, "a1"),
                make_due_reminder(fail_id, "a1"),
                make_due_reminder(error_id, "a1"),
            ],
        )

        exit_code = run_due_reminders.main([])

        self.assertEqual(exit_code, run_due_reminders.EXIT_OK)
        reminders = {r["id"]: r for r in self._read(self.reminders_file)}
        self.assertEqual(reminders[ok_id]["status"], "sent")
        self.assertEqual(reminders[fail_id]["status"], "failed")
        self.assertEqual(reminders[fail_id]["failureReason"], "send_failed")
        self.assertEqual(reminders[error_id]["status"], "failed")
        self.assertEqual(reminders[error_id]["failureReason"], "send_failed")

    def test_terminal_reminder_is_not_reprocessed(self):
        already_sent = make_due_reminder("r-sent", "a1")
        already_sent["status"] = "sent"
        already_sent["sentAt"] = "2020-01-01T00:00:00+00:00"
        self._write(self.appointments_file, [make_active_appointment("a1")])
        self._write(self.reminders_file, [already_sent])

        exit_code = run_due_reminders.main([])

        self.assertEqual(exit_code, run_due_reminders.EXIT_OK)
        reminders = self._read(self.reminders_file)
        self.assertEqual(reminders[0]["status"], "sent")
        self.assertEqual(reminders[0]["sentAt"], "2020-01-01T00:00:00+00:00")

    def test_real_repository_data_files_are_not_modified(self):
        real_reminders_path = os.path.join(os.path.dirname(reminder_service.__file__), "reminders.json")
        real_appointments_path = os.path.join(
            os.path.dirname(reminder_service.__file__), "appointments.json"
        )
        with open(real_reminders_path) as f:
            before_reminders = f.read()
        with open(real_appointments_path) as f:
            before_appointments = f.read()

        self._write(self.appointments_file, [make_active_appointment("a1")])
        self._write(self.reminders_file, [make_due_reminder("r-ok", "a1")])
        run_due_reminders.main([])

        with open(real_reminders_path) as f:
            after_reminders = f.read()
        with open(real_appointments_path) as f:
            after_appointments = f.read()
        self.assertEqual(before_reminders, after_reminders)
        self.assertEqual(before_appointments, after_appointments)


class NowOverrideTest(unittest.TestCase):
    """Tests for --now (Phase 6.2-G) - a pass-through to reminder_service's
    own existing `now=` parameter (get_due_reminders()/process_due_reminders()),
    never new due-detection logic of any kind. reminder_service itself is
    still mocked here, since these tests are only about whether the right
    value reaches it - see NowOverrideEndToEndTest below for a real,
    unmocked state-transition proof.
    """

    @patch.object(run_due_reminders.reminder_service, "process_due_reminders")
    @patch.object(run_due_reminders.reminder_service, "get_due_reminders", return_value=[])
    def test_now_omitted_passes_none_to_get_due_reminders(self, mock_get_due, mock_process):
        exit_code = run_due_reminders.main(["--dry-run"])

        self.assertEqual(exit_code, 0)
        mock_get_due.assert_called_once_with(now=None)
        mock_process.assert_not_called()

    @patch.object(run_due_reminders.reminder_service, "process_due_reminders")
    @patch.object(run_due_reminders.reminder_service, "get_due_reminders", return_value=[])
    def test_now_flag_is_passed_through_to_get_due_reminders_in_dry_run(
        self, mock_get_due, mock_process
    ):
        exit_code = run_due_reminders.main(["--dry-run", "--now", "2027-06-02T00:00:00+00:00"])

        self.assertEqual(exit_code, 0)
        mock_get_due.assert_called_once_with(now=datetime(2027, 6, 2, 0, 0, 0, tzinfo=timezone.utc))
        mock_process.assert_not_called()

    @patch.object(run_due_reminders.reminder_service, "process_due_reminders", return_value=[])
    def test_now_flag_is_passed_through_to_process_due_reminders_in_mutating_mode(self, mock_process):
        with patch.dict("os.environ", {"NOTIFICATION_PROVIDER": "mock"}):
            exit_code = run_due_reminders.main(["--now", "2027-06-02T00:00:00+00:00"])

        self.assertEqual(exit_code, run_due_reminders.EXIT_OK)
        mock_process.assert_called_once_with(
            send=mock_notification_provider.send,
            now=datetime(2027, 6, 2, 0, 0, 0, tzinfo=timezone.utc),
        )

    def test_malformed_now_value_is_rejected(self):
        with self.assertRaises(SystemExit):
            run_due_reminders.main(["--dry-run", "--now", "not-a-timestamp"])

    def test_timezone_naive_now_value_is_rejected(self):
        with self.assertRaises(SystemExit):
            run_due_reminders.main(["--dry-run", "--now", "2027-06-02T00:00:00"])


class NowOverrideEndToEndTest(unittest.TestCase):
    """Real pipeline, real (unmocked) reminder_service.process_due_reminders()
    - mirrors MockProviderEndToEndTest's own isolation pattern above -
    proving --now actually changes what gets processed, not merely that
    the right argument value was received.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.reminders_file = os.path.join(self.tmp_dir.name, "reminders.json")
        self.appointments_file = os.path.join(self.tmp_dir.name, "appointments.json")

        patchers = [
            patch.object(reminder_service, "REMINDERS_FILE", self.reminders_file),
            patch.object(reminder_service, "APPOINTMENTS_FILE", self.appointments_file),
            patch.dict("os.environ", {"NOTIFICATION_PROVIDER": "mock"}),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _write(self, path, data):
        with open(path, "w") as f:
            json.dump(data, f)

    def _read(self, path):
        with open(path) as f:
            return json.load(f)

    def test_now_override_makes_a_future_reminder_due_and_processes_it(self):
        # sendAt is a genuinely future instant relative to this environment's
        # real wall-clock time, so without --now this reminder is not due.
        future_reminder = make_due_reminder("r-ok", "a1")
        future_reminder["sendAt"] = "2027-06-01T00:00:00+00:00"
        self._write(self.appointments_file, [make_active_appointment("a1")])
        self._write(self.reminders_file, [future_reminder])

        exit_code = run_due_reminders.main([])
        self.assertEqual(exit_code, run_due_reminders.EXIT_OK)
        self.assertEqual(self._read(self.reminders_file)[0]["status"], "pending")

        exit_code = run_due_reminders.main(["--now", "2027-06-02T00:00:00+00:00"])
        self.assertEqual(exit_code, run_due_reminders.EXIT_OK)
        reminders = self._read(self.reminders_file)
        self.assertEqual(reminders[0]["status"], "sent")
        self.assertIsNotNone(reminders[0]["sentAt"])


if __name__ == "__main__":
    unittest.main()
