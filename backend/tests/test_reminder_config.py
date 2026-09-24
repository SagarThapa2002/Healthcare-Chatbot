"""Tests for backend/reminder_config.py (Phase 6.2-A).

Every test patches os.environ directly (via unittest.mock.patch.dict) so
none of them depend on - or alter - whatever CLINIC_TIMEZONE happens to be
set in the real environment running this suite.
"""
import unittest
from unittest.mock import patch

from backend import reminder_config


class ClinicTimezoneTest(unittest.TestCase):
    def test_missing_clinic_timezone_raises(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(reminder_config.ReminderConfigError):
                reminder_config.get_clinic_timezone()

    def test_blank_clinic_timezone_raises(self):
        with patch.dict('os.environ', {'CLINIC_TIMEZONE': '   '}, clear=False):
            with self.assertRaises(reminder_config.ReminderConfigError):
                reminder_config.get_clinic_timezone()

    def test_invalid_clinic_timezone_raises(self):
        with patch.dict('os.environ', {'CLINIC_TIMEZONE': 'Not/AZone'}, clear=False):
            with self.assertRaises(reminder_config.ReminderConfigError):
                reminder_config.get_clinic_timezone()

    def test_valid_clinic_timezone_returns_zoneinfo(self):
        with patch.dict('os.environ', {'CLINIC_TIMEZONE': 'Europe/London'}, clear=False):
            tz = reminder_config.get_clinic_timezone()
        self.assertEqual(str(tz), 'Europe/London')

    def test_never_depends_on_the_process_os_timezone(self):
        # Setting the process's own `TZ` environment variable (what a bare
        # datetime.now() with no tz argument would be influenced by) must
        # have zero effect on the zone CLINIC_TIMEZONE resolves to - this
        # is the concrete guarantee that the reminder system never
        # silently depends on wherever the server happens to be running.
        with patch.dict(
            'os.environ',
            {'CLINIC_TIMEZONE': 'Europe/London', 'TZ': 'America/New_York'},
            clear=False,
        ):
            tz = reminder_config.get_clinic_timezone()
        self.assertEqual(str(tz), 'Europe/London')

    def test_raises_reminder_config_error_specifically_not_bare_value_error(self):
        # ReminderConfigError IS a ValueError (matches ProviderDataError/
        # AvailabilityError's own convention), but callers that only catch
        # the specific type must still be able to.
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(reminder_config.ReminderConfigError):
                reminder_config.get_clinic_timezone()


if __name__ == '__main__':
    unittest.main()
