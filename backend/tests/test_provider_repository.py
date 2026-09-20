"""Tests for backend/provider_repository.py.

Every provider/availability fixture below is SYNTHETIC TEST DATA, written
only to exercise loading/validation mechanics - none of it is real provider
or patient information. See backend/PROVIDER_AVAILABILITY_NOTES.md for what
the real backend/providers.json / backend/provider_availability.json
contain, and what this module is (and isn't) meant to support yet.
"""
import json
import os
import tempfile
import unittest

from backend import provider_repository
from backend.provider_repository import (
    ProviderDataError,
    find_provider,
    get_provider_availability,
    list_providers,
    load_availability,
    load_providers,
    validate_all,
)


def make_provider(provider_id="test-provider", name="Dr. Test", specialty="Test Specialty", location="Test Clinic"):
    return {"id": provider_id, "name": name, "specialty": specialty, "location": location}


def make_availability(provider_id="test-provider", day="Monday", start="09:00", end="17:00", slot_minutes=30):
    return {
        "providerId": provider_id,
        "dayOfWeek": day,
        "startTime": start,
        "endTime": end,
        "slotMinutes": slot_minutes,
    }


def write_json_file(tmp_dir, filename, data):
    path = os.path.join(tmp_dir, filename)
    with open(path, 'w') as f:
        json.dump(data, f)
    return path


class LoadProvidersTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

    def test_valid_providers_file_loads_successfully(self):
        path = write_json_file(self.tmp_dir.name, 'providers.json', [make_provider()])
        providers = load_providers(path=path)
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["id"], "test-provider")

    def test_missing_file_raises(self):
        with self.assertRaises(ProviderDataError):
            load_providers(path=os.path.join(self.tmp_dir.name, 'does-not-exist.json'))

    def test_malformed_json_raises(self):
        path = os.path.join(self.tmp_dir.name, 'bad.json')
        with open(path, 'w') as f:
            f.write("{not valid json")
        with self.assertRaises(ProviderDataError):
            load_providers(path=path)

    def test_wrong_top_level_type_raises(self):
        path = write_json_file(self.tmp_dir.name, 'providers.json', {"not": "a list"})
        with self.assertRaises(ProviderDataError):
            load_providers(path=path)

    def test_missing_required_field_raises(self):
        bad = make_provider()
        del bad["specialty"]
        path = write_json_file(self.tmp_dir.name, 'providers.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_providers(path=path)

    def test_blank_required_field_raises(self):
        bad = make_provider(location="   ")
        path = write_json_file(self.tmp_dir.name, 'providers.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_providers(path=path)

    def test_non_string_required_field_raises(self):
        bad = make_provider()
        bad["name"] = 123
        path = write_json_file(self.tmp_dir.name, 'providers.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_providers(path=path)

    def test_malformed_provider_entry_type_raises(self):
        path = write_json_file(self.tmp_dir.name, 'providers.json', ["not-an-object"])
        with self.assertRaises(ProviderDataError):
            load_providers(path=path)

    def test_duplicate_provider_ids_raise(self):
        path = write_json_file(
            self.tmp_dir.name, 'providers.json',
            [make_provider(provider_id="dup"), make_provider(provider_id="dup")],
        )
        with self.assertRaises(ProviderDataError):
            load_providers(path=path)


class FindAndListProvidersTest(unittest.TestCase):
    def setUp(self):
        self.providers = [
            make_provider(provider_id="dr-a", name="Dr. A"),
            make_provider(provider_id="dr-b", name="Dr. B"),
        ]

    def test_list_providers_returns_every_provider_in_file_order(self):
        result = list_providers(providers=self.providers)
        self.assertEqual([p["id"] for p in result], ["dr-a", "dr-b"])

    def test_find_provider_returns_the_matching_provider(self):
        result = find_provider("dr-b", providers=self.providers)
        self.assertEqual(result["name"], "Dr. B")

    def test_find_provider_returns_none_for_unknown_id(self):
        result = find_provider("does-not-exist", providers=self.providers)
        self.assertIsNone(result)


class LoadAvailabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.providers = [make_provider(provider_id="dr-a")]

    def test_valid_availability_file_loads_successfully(self):
        path = write_json_file(self.tmp_dir.name, 'availability.json', [make_availability(provider_id="dr-a")])
        availability = load_availability(path=path, providers=self.providers)
        self.assertEqual(len(availability), 1)
        self.assertEqual(availability[0]["dayOfWeek"], "Monday")

    def test_missing_file_raises(self):
        with self.assertRaises(ProviderDataError):
            load_availability(
                path=os.path.join(self.tmp_dir.name, 'does-not-exist.json'), providers=self.providers
            )

    def test_malformed_json_raises(self):
        path = os.path.join(self.tmp_dir.name, 'bad.json')
        with open(path, 'w') as f:
            f.write("[not valid json")
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)

    def test_wrong_top_level_type_raises(self):
        path = write_json_file(self.tmp_dir.name, 'availability.json', {"not": "a list"})
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)

    def test_missing_required_field_raises(self):
        bad = make_availability(provider_id="dr-a")
        del bad["slotMinutes"]
        path = write_json_file(self.tmp_dir.name, 'availability.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)

    def test_unknown_provider_id_is_rejected(self):
        bad = make_availability(provider_id="does-not-exist")
        path = write_json_file(self.tmp_dir.name, 'availability.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)

    def test_invalid_weekday_is_rejected(self):
        bad = make_availability(provider_id="dr-a", day="Someday")
        path = write_json_file(self.tmp_dir.name, 'availability.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)

    def test_malformed_start_time_is_rejected(self):
        bad = make_availability(provider_id="dr-a", start="9am")
        path = write_json_file(self.tmp_dir.name, 'availability.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)

    def test_malformed_end_time_is_rejected(self):
        bad = make_availability(provider_id="dr-a", end="25:00")
        path = write_json_file(self.tmp_dir.name, 'availability.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)

    def test_end_time_equal_to_start_time_is_rejected(self):
        bad = make_availability(provider_id="dr-a", start="09:00", end="09:00")
        path = write_json_file(self.tmp_dir.name, 'availability.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)

    def test_end_time_before_start_time_is_rejected(self):
        bad = make_availability(provider_id="dr-a", start="17:00", end="09:00")
        path = write_json_file(self.tmp_dir.name, 'availability.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)

    def test_zero_slot_minutes_is_rejected(self):
        bad = make_availability(provider_id="dr-a", slot_minutes=0)
        path = write_json_file(self.tmp_dir.name, 'availability.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)

    def test_negative_slot_minutes_is_rejected(self):
        bad = make_availability(provider_id="dr-a", slot_minutes=-15)
        path = write_json_file(self.tmp_dir.name, 'availability.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)

    def test_non_integer_slot_minutes_is_rejected(self):
        bad = make_availability(provider_id="dr-a", slot_minutes=30.5)
        path = write_json_file(self.tmp_dir.name, 'availability.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)

    def test_boolean_slot_minutes_is_rejected(self):
        # bool is a subclass of int - confirms True/False aren't silently
        # accepted as a slotMinutes value, round-tripped through real JSON.
        bad = make_availability(provider_id="dr-a", slot_minutes=True)
        path = write_json_file(self.tmp_dir.name, 'availability.json', [bad])
        with self.assertRaises(ProviderDataError):
            load_availability(path=path, providers=self.providers)


class GetProviderAvailabilityTest(unittest.TestCase):
    def test_returns_only_the_matching_providers_windows_in_file_order(self):
        availability = [
            make_availability(provider_id="dr-a", day="Monday"),
            make_availability(provider_id="dr-b", day="Tuesday"),
            make_availability(provider_id="dr-a", day="Wednesday"),
        ]
        result = get_provider_availability("dr-a", availability=availability)
        self.assertEqual([entry["dayOfWeek"] for entry in result], ["Monday", "Wednesday"])

    def test_unknown_provider_id_returns_empty_list_not_an_error(self):
        availability = [make_availability(provider_id="dr-a")]
        result = get_provider_availability("does-not-exist", availability=availability)
        self.assertEqual(result, [])


class RepositoryDoesNotMutateDataFilesTest(unittest.TestCase):
    """Every repository function only ever opens files in 'r' mode, but this
    proves it end-to-end: exercising the full public API against real
    on-disk files and confirming their bytes are byte-for-byte identical
    afterward - not just that no code path happens to call a 'w'-mode open.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

        self.providers_path = write_json_file(
            self.tmp_dir.name, 'providers.json', [make_provider(provider_id="dr-a")]
        )
        self.availability_path = write_json_file(
            self.tmp_dir.name, 'availability.json', [make_availability(provider_id="dr-a")]
        )

    @staticmethod
    def _read_bytes(path):
        with open(path, 'rb') as f:
            return f.read()

    def test_full_api_usage_leaves_temp_fixture_files_byte_for_byte_unchanged(self):
        providers_before = self._read_bytes(self.providers_path)
        availability_before = self._read_bytes(self.availability_path)

        providers, availability = validate_all(
            providers_path=self.providers_path, availability_path=self.availability_path
        )
        list_providers(providers=providers)
        find_provider("dr-a", providers=providers)
        find_provider("does-not-exist", providers=providers)
        get_provider_availability("dr-a", availability=availability)

        self.assertEqual(self._read_bytes(self.providers_path), providers_before)
        self.assertEqual(self._read_bytes(self.availability_path), availability_before)

    def test_production_data_files_are_untouched_by_validation(self):
        # Exercises the REAL backend/providers.json and
        # backend/provider_availability.json - proves validate_all() with
        # no path arguments (the normal call shape) never writes to the
        # actual production data files, not just the temp fixtures above.
        before_providers = self._read_bytes(provider_repository.PROVIDERS_FILE)
        before_availability = self._read_bytes(provider_repository.AVAILABILITY_FILE)

        validate_all()

        self.assertEqual(self._read_bytes(provider_repository.PROVIDERS_FILE), before_providers)
        self.assertEqual(self._read_bytes(provider_repository.AVAILABILITY_FILE), before_availability)


class ProductionProviderDataFileTest(unittest.TestCase):
    """Mirrors symptom_triage.py's ProductionRulesFileTest convention:
    proves the real backend/providers.json and
    backend/provider_availability.json are valid, not just that the
    validation logic works against synthetic fixtures above.
    """

    def test_production_files_are_valid(self):
        providers, availability = validate_all()
        self.assertGreaterEqual(len(providers), 2)
        self.assertGreaterEqual(len(availability), 1)

    def test_every_production_provider_has_at_least_one_availability_window(self):
        providers, availability = validate_all()
        for provider in providers:
            with self.subTest(provider=provider["id"]):
                windows = get_provider_availability(provider["id"], availability=availability)
                self.assertTrue(windows, f"provider {provider['id']!r} has no availability windows")


if __name__ == '__main__':
    unittest.main()
