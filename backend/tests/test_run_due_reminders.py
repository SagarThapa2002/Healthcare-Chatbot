"""Tests for backend/run_due_reminders.py (Phase 6.2-D).

Every test calls main(argv) directly, in-process - never a real
subprocess - and mocks/patches backend.run_due_reminders.reminder_service
so nothing here ever touches a real or even a temp reminders.json/
appointments.json. This module owns no domain logic of its own (see its
own docstring), so these tests are only about the CLI boundary itself:
argument parsing, dispatch, exit codes, and logged content - never
reminder eligibility/state-transition behavior, which is already fully
covered by backend/tests/test_reminder_service.py.
"""
import unittest
from unittest.mock import patch

from backend import run_due_reminders


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
        mock_get_due.assert_called_once_with()
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
    @patch.object(run_due_reminders.reminder_service, "process_due_reminders")
    @patch.object(run_due_reminders.reminder_service, "get_due_reminders")
    def test_normal_invocation_with_no_sender_exits_non_zero_and_mutates_nothing(
        self, mock_get_due, mock_process
    ):
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
        with self.assertLogs(run_due_reminders.logger, level="ERROR") as captured:
            run_due_reminders.main([])

        self.assertTrue(any("no notification sender" in line.lower() for line in captured.output))
        mock_process.assert_not_called()


class ArgvHandlingTest(unittest.TestCase):
    @patch.object(run_due_reminders.reminder_service, "get_due_reminders", return_value=[])
    def test_argv_none_uses_normal_argparse_behavior(self, mock_get_due):
        # With argv=None and no --dry-run present in the real process
        # argv, argparse falls back to sys.argv[1:] - under the test
        # runner that is empty/irrelevant flags, so this exercises the
        # same "normal invocation, no sender" path deterministically.
        with patch("sys.argv", ["run_due_reminders"]):
            exit_code = run_due_reminders.main(None)

        self.assertEqual(exit_code, run_due_reminders.EXIT_NO_SENDER_CONFIGURED)

    @patch.object(run_due_reminders.reminder_service, "get_due_reminders", return_value=[])
    def test_argv_none_with_dry_run_flag_in_sys_argv(self, mock_get_due):
        with patch("sys.argv", ["run_due_reminders", "--dry-run"]):
            exit_code = run_due_reminders.main(None)

        self.assertEqual(exit_code, 0)
        mock_get_due.assert_called_once_with()

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


if __name__ == "__main__":
    unittest.main()
