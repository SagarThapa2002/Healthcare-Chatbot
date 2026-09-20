"""Tests for backend/availability_service.py.

Every provider/availability/appointment fixture below is SYNTHETIC TEST
DATA, written only to exercise slot-generation and conflict-detection
mechanics - none of it is real provider, clinic, or patient information.
"providers"/"availability" are always passed explicitly so these tests
never depend on the real backend/providers.json /
backend/provider_availability.json contents; only the small dedicated
"production data" class at the bottom reads the real files, and only to
prove they are never mutated.
"""
import json
import os
import tempfile
import unittest

from backend import availability_service
from backend.availability_service import (
    AvailabilityError,
    get_available_slots,
    is_slot_available,
)

# 2026-09-21 is a Monday - used throughout as the canonical test date so
# every fixture's dayOfWeek: "Monday" lines up with it.
MONDAY = "2026-09-21"
TUESDAY = "2026-09-22"


def make_provider(provider_id="dr-a", name="Dr. A", specialty="Test Specialty", location="Test Clinic"):
    return {"id": provider_id, "name": name, "specialty": specialty, "location": location}


def make_window(provider_id="dr-a", day="Monday", start="09:00", end="17:00", slot_minutes=30):
    return {
        "providerId": provider_id,
        "dayOfWeek": day,
        "startTime": start,
        "endTime": end,
        "slotMinutes": slot_minutes,
    }


def make_appointment(
    provider_id="dr-a", date=MONDAY, time="10:00", name="Test Patient",
    status=None, duration_minutes=None, omit_provider_id=False,
):
    appointment = {"name": name, "date": date, "time": time}
    if not omit_provider_id:
        appointment["providerId"] = provider_id
    if status is not None:
        appointment["status"] = status
    if duration_minutes is not None:
        appointment["durationMinutes"] = duration_minutes
    return appointment


DEFAULT_PROVIDERS = [make_provider()]
DEFAULT_WINDOWS = [make_window()]


class SlotGenerationTest(unittest.TestCase):
    def test_normal_weekday_generates_expected_slots(self):
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertEqual(len(slots), 16)
        self.assertEqual(slots[0], "09:00")

    def test_final_slot_fits_exactly_within_availability(self):
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertIn("16:30", slots)
        self.assertEqual(slots[-1], "16:30")

    def test_final_boundary_itself_is_not_generated_as_start_time(self):
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertNotIn("17:00", slots)

    def test_no_availability_returns_empty_list(self):
        # DEFAULT_WINDOWS only configures Monday - Tuesday has nothing.
        slots = get_available_slots(
            "dr-a", TUESDAY, appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertEqual(slots, [])

    def test_multiple_availability_windows_work(self):
        windows = [
            make_window(start="09:00", end="12:00"),
            make_window(start="13:00", end="17:00"),
        ]
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=[], providers=DEFAULT_PROVIDERS, availability=windows
        )
        self.assertIn("09:00", slots)
        self.assertIn("11:30", slots)
        self.assertIn("13:00", slots)
        self.assertIn("16:30", slots)
        self.assertEqual(len(slots), 14)

    def test_lunch_gap_does_not_generate_slots(self):
        windows = [
            make_window(start="09:00", end="12:00"),
            make_window(start="13:00", end="17:00"),
        ]
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=[], providers=DEFAULT_PROVIDERS, availability=windows
        )
        self.assertNotIn("12:00", slots)
        self.assertNotIn("12:30", slots)

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(AvailabilityError):
            get_available_slots(
                "does-not-exist", MONDAY, appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
            )

    def test_invalid_date_rejected(self):
        with self.assertRaises(AvailabilityError):
            get_available_slots(
                "dr-a", "2026-02-30", appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
            )

    def test_invalid_date_format_rejected(self):
        with self.assertRaises(AvailabilityError):
            get_available_slots(
                "dr-a", "09-21-2026", appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
            )

    def test_invalid_time_configuration_rejected(self):
        # A hand-built window with a malformed startTime, bypassing
        # provider_repository's own upstream validation entirely - proves
        # availability_service defensively validates window times itself
        # rather than blindly trusting its input.
        bad_windows = [make_window(start="9:00")]
        with self.assertRaises(AvailabilityError):
            get_available_slots(
                "dr-a", MONDAY, appointments=[], providers=DEFAULT_PROVIDERS, availability=bad_windows
            )

    def test_overlapping_windows_are_rejected(self):
        windows = [
            make_window(start="09:00", end="13:00"),
            make_window(start="12:00", end="17:00"),
        ]
        with self.assertRaises(AvailabilityError):
            get_available_slots(
                "dr-a", MONDAY, appointments=[], providers=DEFAULT_PROVIDERS, availability=windows
            )

    def test_touching_windows_are_allowed_and_generate_independent_slots(self):
        windows = [
            make_window(start="09:00", end="12:00", slot_minutes=60),
            make_window(start="12:00", end="14:00", slot_minutes=60),
        ]
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=[], providers=DEFAULT_PROVIDERS, availability=windows
        )
        self.assertEqual(slots, ["09:00", "10:00", "11:00", "12:00", "13:00"])


class ConflictDetectionTest(unittest.TestCase):
    def test_booked_appointment_blocks_matching_slot(self):
        appointments = [make_appointment(time="10:00", duration_minutes=30)]
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertNotIn("10:00", slots)

    def test_booked_appointment_blocks_overlapping_slot(self):
        # 10:00-11:00 must block the 10:30 candidate (10:30-11:00), even
        # though 10:30 is not the appointment's own start time.
        appointments = [make_appointment(time="10:00", duration_minutes=60)]
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertNotIn("10:00", slots)
        self.assertNotIn("10:30", slots)
        self.assertIn("09:30", slots)
        self.assertIn("11:00", slots)

    def test_cancelled_appointment_does_not_block_slot(self):
        appointments = [make_appointment(time="10:00", duration_minutes=30, status="cancelled")]
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertIn("10:00", slots)

    def test_different_provider_appointment_does_not_block_slot(self):
        appointments = [make_appointment(provider_id="dr-b", time="10:00", duration_minutes=30)]
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertIn("10:00", slots)

    def test_legacy_appointment_without_provider_id_does_not_block_provider_slot(self):
        appointments = [make_appointment(time="10:00", duration_minutes=30, omit_provider_id=True)]
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertIn("10:00", slots)

    def test_legacy_appointment_without_duration_uses_slot_duration(self):
        # No durationMinutes given - must default to this window's
        # slotMinutes (30), blocking exactly 10:00-10:30, not more.
        appointments = [make_appointment(time="10:00")]
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertNotIn("10:00", slots)
        self.assertIn("10:30", slots)

    def test_explicit_duration_is_respected(self):
        appointments = [make_appointment(time="10:00", duration_minutes=90)]
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertNotIn("10:00", slots)
        self.assertNotIn("10:30", slots)
        self.assertNotIn("11:00", slots)
        self.assertIn("11:30", slots)

    def test_back_to_back_appointments_are_allowed(self):
        appointments = [make_appointment(time="10:00", duration_minutes=30)]
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertIn("10:30", slots)

    def test_invalid_appointment_status_is_rejected(self):
        appointments = [make_appointment(time="10:00", status="pending")]
        with self.assertRaises(AvailabilityError):
            get_available_slots(
                "dr-a", MONDAY, appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
            )

    def test_invalid_duration_is_rejected(self):
        appointments = [make_appointment(time="10:00", duration_minutes="30")]
        with self.assertRaises(AvailabilityError):
            get_available_slots(
                "dr-a", MONDAY, appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
            )

    def test_zero_duration_is_rejected(self):
        appointments = [make_appointment(time="10:00", duration_minutes=0)]
        with self.assertRaises(AvailabilityError):
            get_available_slots(
                "dr-a", MONDAY, appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
            )

    def test_irrelevant_appointment_on_a_different_date_is_ignored(self):
        appointments = [make_appointment(date="2026-09-28", time="10:00", duration_minutes=30)]
        slots = get_available_slots(
            "dr-a", MONDAY, appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
        )
        self.assertIn("10:00", slots)


class SpecificSlotValidationTest(unittest.TestCase):
    def test_valid_free_slot_returns_available(self):
        self.assertTrue(
            is_slot_available(
                "dr-a", MONDAY, "09:00", appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
            )
        )

    def test_occupied_slot_returns_unavailable(self):
        appointments = [make_appointment(time="09:00", duration_minutes=30)]
        self.assertFalse(
            is_slot_available(
                "dr-a", MONDAY, "09:00",
                appointments=appointments, providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS,
            )
        )

    def test_outside_availability_returns_unavailable(self):
        self.assertFalse(
            is_slot_available(
                "dr-a", MONDAY, "08:00", appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS
            )
        )

    def test_slot_crossing_availability_boundary_returns_unavailable(self):
        # 60-minute window, 40-minute slots: only "09:00" fits (09:40 would
        # end at 10:20, past the 10:00 boundary) - a grid time that would
        # genuinely cross the boundary if it were allowed.
        windows = [make_window(start="09:00", end="10:00", slot_minutes=40)]
        self.assertTrue(
            is_slot_available(
                "dr-a", MONDAY, "09:00", appointments=[], providers=DEFAULT_PROVIDERS, availability=windows
            )
        )
        self.assertFalse(
            is_slot_available(
                "dr-a", MONDAY, "09:40", appointments=[], providers=DEFAULT_PROVIDERS, availability=windows
            )
        )

    def test_malformed_date_rejected(self):
        with self.assertRaises(AvailabilityError):
            is_slot_available(
                "dr-a", "2026-02-30", "09:00",
                appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS,
            )

    def test_malformed_time_rejected(self):
        with self.assertRaises(AvailabilityError):
            is_slot_available(
                "dr-a", MONDAY, "25:00",
                appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS,
            )

    def test_single_digit_hour_time_rejected(self):
        with self.assertRaises(AvailabilityError):
            is_slot_available(
                "dr-a", MONDAY, "9:30",
                appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS,
            )

    def test_unknown_provider_rejected(self):
        with self.assertRaises(AvailabilityError):
            is_slot_available(
                "does-not-exist", MONDAY, "09:00",
                appointments=[], providers=DEFAULT_PROVIDERS, availability=DEFAULT_WINDOWS,
            )


class LoadAppointmentsFileTest(unittest.TestCase):
    """Directly exercises _load_appointments()'s own file-reading rules -
    these are internal details (hence the leading underscore), but this
    codebase's existing tests (e.g. test_symptom_triage.py's
    _UNKNOWN_MESSAGE check) already establish that testing a private
    helper directly is fine when it has behavior worth pinning on its own.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

    def test_missing_file_returns_empty_list(self):
        path = os.path.join(self.tmp_dir.name, 'does-not-exist.json')
        self.assertEqual(availability_service._load_appointments(path=path), [])

    def test_malformed_json_raises(self):
        path = os.path.join(self.tmp_dir.name, 'bad.json')
        with open(path, 'w') as f:
            f.write("[not valid json")
        with self.assertRaises(AvailabilityError):
            availability_service._load_appointments(path=path)

    def test_wrong_top_level_type_raises(self):
        path = os.path.join(self.tmp_dir.name, 'appointments.json')
        with open(path, 'w') as f:
            json.dump({"not": "a list"}, f)
        with self.assertRaises(AvailabilityError):
            availability_service._load_appointments(path=path)

    def test_valid_file_loads_successfully(self):
        path = os.path.join(self.tmp_dir.name, 'appointments.json')
        with open(path, 'w') as f:
            json.dump([make_appointment()], f)
        result = availability_service._load_appointments(path=path)
        self.assertEqual(len(result), 1)


class DoesNotMutateRealDataFilesTest(unittest.TestCase):
    """Proves this module never writes to the real, production
    backend/appointments.json, backend/providers.json, or
    backend/provider_availability.json - exercises the full public API
    with no overrides at all (the normal call shape) and compares bytes
    before/after, not just the absence of a 'w'-mode open() call.
    """

    @staticmethod
    def _read_bytes(path):
        with open(path, 'rb') as f:
            return f.read()

    def test_real_data_files_are_untouched(self):
        from backend import provider_repository

        appointments_before = self._read_bytes(availability_service.APPOINTMENTS_FILE)
        providers_before = self._read_bytes(provider_repository.PROVIDERS_FILE)
        availability_before = self._read_bytes(provider_repository.AVAILABILITY_FILE)

        # "dr-patel" is a real provider (see backend/providers.json) with
        # real Monday availability (see backend/provider_availability.json).
        get_available_slots("dr-patel", MONDAY)
        is_slot_available("dr-patel", MONDAY, "09:00")

        self.assertEqual(self._read_bytes(availability_service.APPOINTMENTS_FILE), appointments_before)
        self.assertEqual(self._read_bytes(provider_repository.PROVIDERS_FILE), providers_before)
        self.assertEqual(self._read_bytes(provider_repository.AVAILABILITY_FILE), availability_before)


if __name__ == '__main__':
    unittest.main()
