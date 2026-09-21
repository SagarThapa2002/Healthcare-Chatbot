"""Tests for the Phase 6.1 Slice 3 booking-availability work in
backend/chatbot_logic.py:

  - Step 1: the standalone formatting helpers _format_provider_list() and
    _format_slot_list().
  - Step 2: the NAME -> PROVIDER -> DATE -> SLOT -> CONFIRM booking
    sequence in _handle_book_appointment() itself, exercised at the full
    webhook level (BookingFlowTestCase below), plus the
    _resolve_provider_choice() / _resolve_slot_choice() /
    _check_date_availability() helpers it's built from.

Kept in their own file, mirroring test_chatbot_logic_llm_routing.py's own
precedent, so the existing, carefully-scoped test_webhook.py is never
touched by the bulk of this work (test_webhook.py's own booking test and
_book_and_confirm() helper were updated separately, minimally, only where
the new mandatory provider/availability checks made their old fixture
data - an unavailable weekday, no provider at all - no longer reach a
confirmable state).

Most Step 1 tests mock the provider_repository/availability_service
boundary so they exercise ONLY the formatting logic; the Step 2 tests use
the real, synthetic backend/providers.json / backend/provider_availability.json
data throughout (via the real webhook, isolating only appointment file
I/O, exactly like test_webhook.py's WebhookTestCase), since the whole
point of this slice is proving the real chain behaves correctly end to
end - not a re-test of availability_service.py's own already-tested
mechanics.
"""
import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import availability_service, chatbot_logic, provider_repository
from backend.chatbot_logic import _format_provider_list, _format_slot_list


def make_provider(provider_id="dr-a", name="Dr. A", specialty="Test Specialty", location="Test Clinic"):
    return {"id": provider_id, "name": name, "specialty": specialty, "location": location}


class FormatProviderListTest(unittest.TestCase):
    def test_provider_formatting_includes_expected_identifying_fields(self):
        providers = [make_provider(name="Dr. A", specialty="General Practice", location="Main Clinic")]
        with patch.object(provider_repository, 'list_providers', return_value=providers):
            result = _format_provider_list()

        self.assertIn("Dr. A", result)
        self.assertIn("General Practice", result)
        self.assertIn("Main Clinic", result)
        self.assertIn("1.", result)

    def test_provider_list_uses_the_repository_not_a_direct_file_read(self):
        # Proves delegation: chatbot_logic.py must obtain providers through
        # provider_repository.list_providers(), never providers.json
        # directly - if this mock isn't consulted, the assertion below on
        # its return value being what's rendered would fail.
        providers = [make_provider(provider_id="only-this-one", name="Only This One")]
        with patch.object(provider_repository, 'list_providers', return_value=providers) as mock_list:
            result = _format_provider_list()

        mock_list.assert_called_once_with()
        self.assertIn("Only This One", result)

    def test_provider_ordering_is_deterministic_and_matches_repository_order(self):
        providers = [
            make_provider(provider_id="dr-z", name="Dr. Z"),
            make_provider(provider_id="dr-a", name="Dr. A"),
        ]
        with patch.object(provider_repository, 'list_providers', return_value=providers):
            result = _format_provider_list()

        # "Dr. Z" (list position 1) must appear before "Dr. A" (position 2)
        # - i.e. repository file order is preserved, never alphabetized.
        self.assertLess(result.index("1. Dr. Z"), result.index("2. Dr. A"))

    def test_repeated_calls_produce_identical_output(self):
        providers = [make_provider()]
        with patch.object(provider_repository, 'list_providers', return_value=providers):
            first = _format_provider_list()
            second = _format_provider_list()
        self.assertEqual(first, second)

    def test_empty_provider_list_is_handled_deterministically(self):
        with patch.object(provider_repository, 'list_providers', return_value=[]):
            result = _format_provider_list()
        self.assertEqual(result, "No providers are currently configured.")

    def test_does_not_mutate_the_data_returned_by_the_repository(self):
        providers = [make_provider(name="Dr. A"), make_provider(provider_id="dr-b", name="Dr. B")]
        before = copy.deepcopy(providers)

        with patch.object(provider_repository, 'list_providers', return_value=providers):
            _format_provider_list()

        self.assertEqual(providers, before)

    def test_real_synthetic_provider_data_all_appear(self):
        # Integration-style: no mocking - exercises the real
        # backend/providers.json via the real provider_repository.
        result = _format_provider_list()
        self.assertIn("Dr. Patel", result)
        self.assertIn("Dr. Nguyen", result)
        self.assertIn("Dr. Okafor", result)

    def test_real_provider_data_file_is_not_mutated(self):
        with open(provider_repository.PROVIDERS_FILE, 'rb') as f:
            before = f.read()

        _format_provider_list()

        with open(provider_repository.PROVIDERS_FILE, 'rb') as f:
            after = f.read()
        self.assertEqual(before, after)


class FormatSlotListTest(unittest.TestCase):
    def test_delegates_to_availability_service_with_the_given_arguments(self):
        with patch.object(availability_service, 'get_available_slots', return_value=["09:00"]) as mock_get:
            _format_slot_list("dr-a", "2026-09-21")

        mock_get.assert_called_once_with("dr-a", "2026-09-21")

    def test_normal_slots_are_formatted_correctly(self):
        with patch.object(availability_service, 'get_available_slots', return_value=["09:00", "09:30", "10:00"]):
            result = _format_slot_list("dr-a", "2026-09-21")

        self.assertEqual(result, "1. 09:00\n2. 09:30\n3. 10:00")

    def test_slot_values_are_used_verbatim_as_local_clinic_time(self):
        # No reformatting/timezone conversion - the exact HH:MM string
        # returned by availability_service must appear unchanged.
        with patch.object(availability_service, 'get_available_slots', return_value=["14:45"]):
            result = _format_slot_list("dr-a", "2026-09-21")
        self.assertIn("14:45", result)

    def test_empty_availability_is_handled_deterministically(self):
        with patch.object(availability_service, 'get_available_slots', return_value=[]):
            result = _format_slot_list("dr-a", "2026-09-21")
        self.assertEqual(result, "No available slots for that date.")

    def test_unknown_provider_error_propagates_per_the_availability_service_contract(self):
        with patch.object(
            availability_service, 'get_available_slots',
            side_effect=availability_service.AvailabilityError("unknown provider: 'does-not-exist'"),
        ):
            with self.assertRaises(availability_service.AvailabilityError):
                _format_slot_list("does-not-exist", "2026-09-21")

    def test_malformed_date_error_propagates_per_the_availability_service_contract(self):
        with patch.object(
            availability_service, 'get_available_slots',
            side_effect=availability_service.AvailabilityError("date is not a valid calendar date"),
        ):
            with self.assertRaises(availability_service.AvailabilityError):
                _format_slot_list("dr-a", "2026-02-30")

    def test_does_not_mutate_the_data_returned_by_availability_service(self):
        slots = ["09:00", "09:30"]
        before = copy.deepcopy(slots)

        with patch.object(availability_service, 'get_available_slots', return_value=slots):
            _format_slot_list("dr-a", "2026-09-21")

        self.assertEqual(slots, before)

    def test_real_synthetic_provider_and_availability_data_produces_expected_slots(self):
        # Integration-style: no mocking - exercises the real
        # backend/providers.json / backend/provider_availability.json /
        # backend/appointments.json chain via the real availability_service.
        # 2026-09-21 is a Monday, and dr-patel's real configured Monday
        # window starts at 09:00 (see backend/provider_availability.json).
        result = _format_slot_list("dr-patel", "2026-09-21")
        self.assertTrue(result.startswith("1. 09:00"))

    def test_real_data_files_are_not_mutated(self):
        appointments_path = availability_service.APPOINTMENTS_FILE
        availability_path = provider_repository.AVAILABILITY_FILE

        with open(appointments_path, 'rb') as f:
            appointments_before = f.read()
        with open(availability_path, 'rb') as f:
            availability_before = f.read()

        _format_slot_list("dr-patel", "2026-09-21")

        with open(appointments_path, 'rb') as f:
            self.assertEqual(f.read(), appointments_before)
        with open(availability_path, 'rb') as f:
            self.assertEqual(f.read(), availability_before)


class BookingFlowTestCase(unittest.TestCase):
    """Base class for full webhook-level Step 2 booking-flow tests -
    isolates appointment file I/O from the real backend/appointments.json,
    exactly like test_webhook.py's WebhookTestCase. Deliberately not
    imported from that file (no cross-file inheritance): this class
    defines no test_* methods of its own, so unittest's inherited-test
    duplication risk (see test_webhook.py's
    UpdateCancelAppointmentMissingNameTest docstring) doesn't apply, but
    keeping this file fully self-contained is simpler to reason about.

    Provider/availability data is NOT mocked here - every test uses the
    real, synthetic backend/providers.json / backend/provider_availability.json
    (dr-patel: Monday & Wednesday, 09:00-17:00, 30-minute slots; dr-nguyen:
    Tuesday & Thursday, 10:00-15:00, 20-minute slots) - see those files.
    2026-12-28 is a Monday and 2026-12-29 is a Tuesday, used throughout so
    fixture dates line up with real provider availability.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

        self.appointments_file = os.path.join(self.tmp_dir.name, 'appointments.json')
        self.pending_file = os.path.join(self.tmp_dir.name, 'pending_appointments.json')
        self.pending_cancellation_file = os.path.join(self.tmp_dir.name, 'pending_cancellation.json')
        self.pending_update_file = os.path.join(self.tmp_dir.name, 'pending_update.json')

        # chatbot_logic.py and availability_service.py each independently
        # compute their own APPOINTMENTS_FILE constant (both point at the
        # same real file by default) - both must be patched, or
        # get_available_slots()/is_slot_available() (called with no
        # explicit `appointments` override, inside _check_date_availability
        # / _resolve_slot_choice) would silently read the real, unmocked
        # backend/appointments.json instead of this test's isolated data.
        # PENDING_CANCELLATION_FILE/PENDING_UPDATE_FILE must also be
        # patched - handle_webhook_request checks their existence on every
        # YesIntent/NoIntent to decide whether to route to the
        # cancellation/update confirm handlers, so leaving either
        # unpatched would have that check silently hit the real repo path
        # instead of this isolated one.
        patcher_appointments = patch.object(chatbot_logic, 'APPOINTMENTS_FILE', self.appointments_file)
        patcher_pending = patch.object(chatbot_logic, 'PENDING_FILE', self.pending_file)
        patcher_pending_cancellation = patch.object(
            chatbot_logic, 'PENDING_CANCELLATION_FILE', self.pending_cancellation_file
        )
        patcher_pending_update = patch.object(
            chatbot_logic, 'PENDING_UPDATE_FILE', self.pending_update_file
        )
        patcher_availability_appointments = patch.object(
            availability_service, 'APPOINTMENTS_FILE', self.appointments_file
        )
        patcher_appointments.start()
        patcher_pending.start()
        patcher_pending_cancellation.start()
        patcher_pending_update.start()
        patcher_availability_appointments.start()
        self.addCleanup(patcher_appointments.stop)
        self.addCleanup(patcher_pending.stop)
        self.addCleanup(patcher_pending_cancellation.stop)
        self.addCleanup(patcher_pending_update.stop)
        self.addCleanup(patcher_availability_appointments.stop)

        self.client = app.test_client()

    def post_webhook(self, intent, parameters=None):
        body = {"queryResult": {"intent": {"displayName": intent}, "parameters": parameters or {}}}
        return self.client.post('/webhook/webhook', json=body)

    def _text(self, response):
        return response.get_json()["messages"][0]["content"]["text"]

    def _fill_every_slot(self, provider_id, date):
        """Seeds the isolated tmp appointments file with one 'booked'
        appointment per slot get_available_slots() would otherwise offer
        for provider_id/date - fully occupying that day using the real
        availability_service.py as the source of truth for which times
        exist, rather than hardcoding a provider's window/slot size here.
        durationMinutes is deliberately omitted so each filler appointment
        defaults to exactly its window's own slotMinutes (Slice 2
        behavior), correctly occupying one slot each regardless of which
        provider is used.
        """
        raw_slots = availability_service.get_available_slots(provider_id, date, appointments=[])
        appointments = [
            {"name": "Filler", "providerId": provider_id, "date": date, "time": slot, "status": "booked"}
            for slot in raw_slots
        ]
        with open(self.appointments_file, 'w') as f:
            json.dump(appointments, f)


class ProviderStageTest(BookingFlowTestCase):
    def test_valid_provider_id_advances_to_date_stage(self):
        response = self.post_webhook("Book Appointment", {"name": "Test Patient", "providerId": "dr-patel"})
        text = self._text(response)
        self.assertIn("Dr. Patel", text)
        self.assertIn("date", text.lower())

    def test_valid_provider_name_advances_to_date_stage(self):
        response = self.post_webhook("Book Appointment", {"name": "Test Patient", "providerId": "Dr. Patel"})
        text = self._text(response)
        self.assertIn("Dr. Patel", text)
        # "Dr. Patel" alone isn't discriminating - the invalid-provider
        # re-prompt also re-displays the full provider list, so it would
        # contain "Dr. Patel" too even if this exact-name match were
        # broken. "date" only appears in the success message.
        self.assertIn("date", text.lower())

    def test_case_insensitive_provider_selection(self):
        response = self.post_webhook("Book Appointment", {"name": "Test Patient", "providerId": "DR. PATEL"})
        text = self._text(response)
        self.assertIn("Dr. Patel", text)
        self.assertIn("date", text.lower())

    def test_valid_numeric_provider_selection(self):
        # "1" must resolve to whichever provider is FIRST in
        # provider_repository.list_providers()'s (file) order - dr-patel,
        # per backend/providers.json.
        response = self.post_webhook("Book Appointment", {"name": "Test Patient", "providerId": "1"})
        text = self._text(response)
        self.assertIn("Dr. Patel", text)
        self.assertIn("date", text.lower())

    def test_invalid_provider_is_rejected_not_silently_accepted(self):
        response = self.post_webhook(
            "Book Appointment", {"name": "Test Patient", "providerId": "Not A Real Doctor"}
        )
        text = self._text(response)
        self.assertNotIn("What date", text)
        self.assertIn("didn't recognize", text.lower())

    def test_provider_list_reappears_after_invalid_selection(self):
        response = self.post_webhook(
            "Book Appointment", {"name": "Test Patient", "providerId": "Not A Real Doctor"}
        )
        text = self._text(response)
        self.assertIn("Dr. Patel", text)
        self.assertIn("Dr. Nguyen", text)
        self.assertIn("Dr. Okafor", text)

    def test_pending_state_is_not_written_at_the_provider_stage(self):
        self.post_webhook("Book Appointment", {"name": "Test Patient", "providerId": "dr-patel"})
        self.assertFalse(os.path.exists(self.pending_file))


class DateStageTest(BookingFlowTestCase):
    def test_provider_with_no_availability_that_weekday_remains_at_date_stage(self):
        # dr-patel is only configured for Monday/Wednesday - Tuesday has
        # no availability window at all.
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-29"},
        )
        text = self._text(response)
        self.assertIn("isn't available", text)
        self.assertIn("Monday", text)
        self.assertIn("Wednesday", text)
        self.assertNotIn("09:00", text)

    def test_provider_with_availability_but_fully_booked_remains_at_date_stage(self):
        self._fill_every_slot("dr-patel", "2026-12-28")
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28"},
        )
        text = self._text(response)
        self.assertIn("fully booked", text.lower())

    def test_valid_provider_and_date_produces_a_slot_list(self):
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28"},
        )
        text = self._text(response)
        self.assertIn("09:00", text)
        self.assertIn("16:30", text)
        self.assertNotIn("17:00", text)

    def test_does_not_advance_to_slot_stage_when_no_availability_that_weekday(self):
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-29"},
        )
        self.assertFalse(os.path.exists(self.pending_file))
        self.assertNotIn("1. ", self._text(response))

    def test_does_not_advance_to_slot_stage_when_fully_booked(self):
        self._fill_every_slot("dr-patel", "2026-12-28")
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28"},
        )
        self.assertFalse(os.path.exists(self.pending_file))


class SlotStageTest(BookingFlowTestCase):
    def test_valid_exact_slot_selection_reaches_confirmation(self):
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        text = self._text(response)
        self.assertIn("yes or no", text)
        self.assertIn("10:00", text)

    def test_valid_numeric_slot_selection(self):
        # "1" must resolve to the FIRST slot get_available_slots() returns
        # for this provider/date - "09:00" for dr-patel's Monday window.
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "1"},
        )
        text = self._text(response)
        self.assertIn("yes or no", text)
        self.assertIn("09:00", text)

    def test_invalid_slot_reprompts_with_the_current_list(self):
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "not-a-time"},
        )
        text = self._text(response)
        self.assertNotIn("yes or no", text)
        self.assertIn("09:00", text)

    def test_slot_outside_availability_window_is_rejected(self):
        response = self.post_webhook(
            "Book Appointment",
            # dr-patel's Monday window ends at 17:00 - never a valid start time.
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "17:00"},
        )
        self.assertNotIn("yes or no", self._text(response))

    def test_slot_that_became_occupied_after_the_list_was_shown_is_rejected(self):
        # First, the slot is genuinely open.
        first = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        self.assertIn("yes or no", self._text(first))
        self.assertTrue(os.path.exists(self.pending_file))

        # Someone else takes it - written directly to the isolated tmp
        # appointments file, exactly as a second real booking would.
        with open(self.appointments_file, 'w') as f:
            json.dump(
                [{"name": "Someone Else", "providerId": "dr-patel", "date": "2026-12-28",
                  "time": "10:00", "status": "booked"}],
                f,
            )

        # Re-submitting the SAME choice must now be rejected, not silently
        # re-confirmed from a stale list.
        second = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        text = self._text(second)
        self.assertNotIn("yes or no", text)
        self.assertIn("isn't available anymore", text)

    def test_pending_state_is_written_only_after_a_valid_slot_selection(self):
        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "not-a-time"},
        )
        self.assertFalse(os.path.exists(self.pending_file))

        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        self.assertTrue(os.path.exists(self.pending_file))

    def test_pending_state_has_the_expected_shape(self):
        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        with open(self.pending_file, 'r') as f:
            pending = json.load(f)
        self.assertEqual(
            pending, {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"}
        )


class ConfirmationStageTest(BookingFlowTestCase):
    def test_full_valid_flow_reaches_the_existing_confirmation_mechanism(self):
        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        booked = self.post_webhook("YesIntent").get_json()
        message = booked["messages"][0]

        self.assertTrue(booked["success"])
        self.assertEqual(message["type"], "booking_confirmation")
        self.assertIn("has been booked", message["content"]["text"])
        self.assertEqual(message["content"]["appointment"]["providerId"], "dr-patel")


class ConfirmationAvailabilityRecheckTest(BookingFlowTestCase):
    """Phase 6.1, Slice 3, Step 3: _handle_yes_intent() now re-validates
    the exact providerId/date/time immediately before persisting, closing
    the race where the slot was available/valid when first selected
    (Step 2) but got taken - or the pending record was otherwise never
    valid - before the user actually confirmed.
    """

    def _write_pending(self, pending):
        with open(self.pending_file, 'w') as f:
            json.dump(pending, f)

    def test_still_available_slot_is_confirmed_successfully(self):
        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        booked = self.post_webhook("YesIntent").get_json()
        message = booked["messages"][0]

        self.assertTrue(booked["success"])
        self.assertEqual(message["type"], "booking_confirmation")
        self.assertIn("has been booked", message["content"]["text"])

    def test_successful_confirmation_still_removes_the_pending_file(self):
        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        self.assertTrue(os.path.exists(self.pending_file))

        self.post_webhook("YesIntent")

        self.assertFalse(os.path.exists(self.pending_file))

    def test_persisted_appointment_contains_the_expected_provider_id(self):
        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        self.post_webhook("YesIntent")

        with open(self.appointments_file, 'r') as f:
            saved = json.load(f)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["providerId"], "dr-patel")

    def test_slot_taken_between_confirmation_prompt_and_yes_is_rejected(self):
        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        self.assertTrue(os.path.exists(self.pending_file))

        # Someone else's booking lands in between - written directly to
        # the isolated tmp appointments file, exactly as a second real
        # booking would. This is the exact race Step 3 is meant to close.
        with open(self.appointments_file, 'w') as f:
            json.dump(
                [{"name": "Someone Else", "providerId": "dr-patel", "date": "2026-12-28",
                  "time": "10:00", "status": "booked"}],
                f,
            )

        response = self.post_webhook("YesIntent")
        data = response.get_json()
        text = data["messages"][0]["content"]["text"]

        self.assertTrue(data["success"])
        self.assertEqual(data["messages"][0]["type"], "text")
        self.assertIn("no longer available", text)

    def test_conflicting_appointment_is_not_overwritten_or_duplicated(self):
        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        conflicting = [{"name": "Someone Else", "providerId": "dr-patel", "date": "2026-12-28",
                         "time": "10:00", "status": "booked"}]
        with open(self.appointments_file, 'w') as f:
            json.dump(conflicting, f)

        self.post_webhook("YesIntent")

        with open(self.appointments_file, 'r') as f:
            saved = json.load(f)
        self.assertEqual(saved, conflicting)

    def test_pending_remains_for_recovery_when_slot_is_rejected(self):
        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        with open(self.pending_file, 'r') as f:
            pending_before = json.load(f)

        with open(self.appointments_file, 'w') as f:
            json.dump(
                [{"name": "Someone Else", "providerId": "dr-patel", "date": "2026-12-28",
                  "time": "10:00", "status": "booked"}],
                f,
            )

        self.post_webhook("YesIntent")

        self.assertTrue(os.path.exists(self.pending_file))
        with open(self.pending_file, 'r') as f:
            pending_after = json.load(f)
        self.assertEqual(pending_after, pending_before)

    def test_pending_missing_provider_id_is_rejected_safely_not_guessed(self):
        # Simulates a stale/legacy pending record predating Step 2's
        # providerId field - never produced by the current
        # _handle_book_appointment, but must still be handled
        # deterministically (never by guessing a provider) if one is
        # ever found on disk.
        self._write_pending({"name": "Test Patient", "date": "2026-12-28", "time": "10:00"})

        response = self.post_webhook("YesIntent")
        data = response.get_json()

        self.assertTrue(data["success"])
        self.assertEqual(data["messages"][0]["type"], "text")
        self.assertIn("missing", data["messages"][0]["content"]["text"].lower())
        self.assertFalse(os.path.exists(self.appointments_file))
        self.assertTrue(os.path.exists(self.pending_file))

    def test_pending_missing_date_is_rejected_safely(self):
        self._write_pending({"name": "Test Patient", "providerId": "dr-patel", "time": "10:00"})

        response = self.post_webhook("YesIntent")
        data = response.get_json()

        self.assertIn("missing", data["messages"][0]["content"]["text"].lower())
        self.assertFalse(os.path.exists(self.appointments_file))

    def test_pending_missing_time_is_rejected_safely(self):
        self._write_pending({"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28"})

        response = self.post_webhook("YesIntent")
        data = response.get_json()

        self.assertIn("missing", data["messages"][0]["content"]["text"].lower())
        self.assertFalse(os.path.exists(self.appointments_file))

    def test_pending_with_unknown_provider_id_is_rejected_safely_not_a_500(self):
        # A providerId that no longer resolves to a real provider (e.g.
        # removed from providers.json since the pending record was
        # written) must go through the existing AvailabilityError
        # handling, not crash or leak internals.
        self._write_pending(
            {"name": "Test Patient", "providerId": "does-not-exist", "date": "2026-12-28", "time": "10:00"}
        )

        response = self.post_webhook("YesIntent")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()

        self.assertTrue(data["success"])
        self.assertEqual(data["messages"][0]["type"], "text")
        text = data["messages"][0]["content"]["text"]
        self.assertNotIn("Traceback", text)
        self.assertNotIn("AvailabilityError", text)
        self.assertFalse(os.path.exists(self.appointments_file))
        self.assertTrue(os.path.exists(self.pending_file))


class BookingErrorHandlingTest(BookingFlowTestCase):
    def test_malformed_date_produces_a_safe_reprompt_not_a_500(self):
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-02-30"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        text = data["messages"][0]["content"]["text"]
        self.assertNotIn("Traceback", text)
        self.assertNotIn("AvailabilityError", text)

    def test_regression_non_booking_intents_are_unaffected(self):
        response = self.post_webhook("General FAQ", {})
        self.assertEqual(response.status_code, 200)
        self.assertIn("virtual healthcare assistant", self._text(response))


class BookingStageContractTest(BookingFlowTestCase):
    """Phase 6.1, Slice 3, Step 4 (revised): proves context.bookingStage is
    reported correctly at every point in the booking flow - structurally,
    not by inspecting message text - so a client can tell "advanced" from
    "rejected, still on this stage" without duplicating the validation
    decisions _handle_book_appointment already makes.
    """

    def _stage(self, response):
        return response.get_json()["context"].get("bookingStage")

    def test_missing_name_reports_name_stage(self):
        response = self.post_webhook("Book Appointment", {})
        self.assertEqual(self._stage(response), "name")

    def test_missing_provider_reports_provider_stage(self):
        response = self.post_webhook("Book Appointment", {"name": "Test Patient"})
        self.assertEqual(self._stage(response), "provider")

    def test_invalid_provider_remains_at_provider_stage(self):
        response = self.post_webhook(
            "Book Appointment", {"name": "Test Patient", "providerId": "Not A Real Doctor"}
        )
        self.assertEqual(self._stage(response), "provider")

    def test_valid_provider_advances_to_date_stage(self):
        response = self.post_webhook("Book Appointment", {"name": "Test Patient", "providerId": "dr-patel"})
        self.assertEqual(self._stage(response), "date")

    def test_missing_date_reports_date_stage(self):
        response = self.post_webhook("Book Appointment", {"name": "Test Patient", "providerId": "dr-patel"})
        self.assertEqual(self._stage(response), "date")

    def test_malformed_date_remains_at_date_stage(self):
        response = self.post_webhook(
            "Book Appointment", {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-02-30"}
        )
        self.assertEqual(self._stage(response), "date")

    def test_no_weekday_availability_remains_at_date_stage(self):
        # dr-patel has no Tuesday availability (see backend/provider_availability.json).
        response = self.post_webhook(
            "Book Appointment", {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-29"}
        )
        self.assertEqual(self._stage(response), "date")

    def test_fully_booked_remains_at_date_stage(self):
        raw_slots = availability_service.get_available_slots("dr-patel", "2026-12-28", appointments=[])
        filler = [
            {"name": "Filler", "providerId": "dr-patel", "date": "2026-12-28", "time": slot, "status": "booked"}
            for slot in raw_slots
        ]
        with open(self.appointments_file, 'w') as f:
            json.dump(filler, f)

        response = self.post_webhook(
            "Book Appointment", {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28"}
        )
        self.assertEqual(self._stage(response), "date")

    def test_valid_date_advances_to_slot_stage(self):
        response = self.post_webhook(
            "Book Appointment", {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28"}
        )
        self.assertEqual(self._stage(response), "slot")

    def test_invalid_slot_remains_at_slot_stage(self):
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "not-a-time"},
        )
        self.assertEqual(self._stage(response), "slot")

    def test_occupied_slot_remains_at_slot_stage(self):
        with open(self.appointments_file, 'w') as f:
            json.dump(
                [{"name": "Someone Else", "providerId": "dr-patel", "date": "2026-12-28",
                  "time": "10:00", "status": "booked"}],
                f,
            )
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        self.assertEqual(self._stage(response), "slot")

    def test_valid_slot_advances_to_confirm_stage(self):
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        self.assertEqual(self._stage(response), "confirm")

    def test_successful_yes_intent_reports_booked_stage(self):
        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        response = self.post_webhook("YesIntent")
        self.assertEqual(self._stage(response), "booked")

    def test_yes_intent_with_no_pending_booking_omits_booking_stage(self):
        response = self.post_webhook("YesIntent")
        self.assertNotIn("bookingStage", response.get_json()["context"])

    def test_yes_intent_race_rejection_omits_booking_stage(self):
        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        with open(self.appointments_file, 'w') as f:
            json.dump(
                [{"name": "Someone Else", "providerId": "dr-patel", "date": "2026-12-28",
                  "time": "10:00", "status": "booked"}],
                f,
            )
        response = self.post_webhook("YesIntent")
        self.assertNotIn("bookingStage", response.get_json()["context"])

    def test_non_booking_intents_never_carry_a_booking_stage(self):
        for intent, params in [
            ("General FAQ", {}),
            ("Symptom Check", {"symptom": "a headache"}),
            ("Update Appointment", {"name": "Test Patient"}),
            ("Cancel Appointment", {"name": "Test Patient"}),
            ("View Appointments", {}),
        ]:
            with self.subTest(intent=intent):
                response = self.post_webhook(intent, params)
                self.assertNotIn("bookingStage", response.get_json()["context"])


class AppointmentIdTest(BookingFlowTestCase):
    """Next Phase 6.1 slice: a stable, server-generated `id` is attached to
    every newly created appointment. Deliberately does NOT touch
    update/cancel/view - those still operate by name only; wiring them to
    use `id` is a separate, later step.
    """

    def _book_and_confirm(self, name="Test Patient", date="2026-12-28", time="10:00"):
        self.post_webhook(
            "Book Appointment", {"name": name, "providerId": "dr-patel", "date": date, "time": time}
        )
        return self.post_webhook("YesIntent").get_json()

    def test_persisted_appointment_has_a_non_empty_id(self):
        self._book_and_confirm()
        with open(self.appointments_file, 'r') as f:
            saved = json.load(f)
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0].get("id"))

    def test_confirmation_response_id_matches_the_persisted_id(self):
        booked = self._book_and_confirm()
        response_id = booked["messages"][0]["content"]["appointment"]["id"]

        with open(self.appointments_file, 'r') as f:
            saved = json.load(f)
        self.assertEqual(saved[0]["id"], response_id)

    def test_two_separate_bookings_get_different_ids(self):
        first = self._book_and_confirm(name="Test Patient", date="2026-12-28", time="10:00")
        second = self._book_and_confirm(name="Test Patient", date="2026-12-28", time="10:30")

        first_id = first["messages"][0]["content"]["appointment"]["id"]
        second_id = second["messages"][0]["content"]["appointment"]["id"]
        self.assertNotEqual(first_id, second_id)

    def test_id_is_not_written_to_the_pending_file(self):
        # id is only assigned at the final, confirmed-creation step in
        # _handle_yes_intent - the pending record itself never has one.
        self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
        with open(self.pending_file, 'r') as f:
            pending = json.load(f)
        self.assertNotIn("id", pending)

    def test_legacy_appointment_without_an_id_is_still_listed_correctly(self):
        # Simulates a pre-existing legacy record (no id, no providerId) -
        # never migrated or backfilled - alongside a newly created one.
        with open(self.appointments_file, 'w') as f:
            json.dump([{"name": "Legacy Patient", "date": "2026-01-01", "time": "09:00"}], f)

        response = self.post_webhook("View Appointments")
        text = response.get_json()["messages"][0]["content"]["text"]
        self.assertIn("Legacy Patient", text)

    def test_legacy_appointment_without_an_id_can_still_be_cancelled_by_name(self):
        with open(self.appointments_file, 'w') as f:
            json.dump([{"name": "Legacy Patient", "date": "2026-01-01", "time": "09:00"}], f)

        identify = self.post_webhook("Cancel Appointment", {"name": "Legacy Patient"})
        self.assertIn("yes or no", identify.get_json()["messages"][0]["content"]["text"])

        confirmed = self.post_webhook("YesIntent")
        text = confirmed.get_json()["messages"][0]["content"]["text"]
        self.assertIn("has been cancelled", text)


class CancellationFlowTest(BookingFlowTestCase):
    """Next Phase 6.1 slice: safe, confirmed, ID-preferring cancellation -
    replaces the previous hard-delete-by-name flow with status="cancelled"
    plus explicit confirmation. Every test seeds data via the isolated tmp
    files from BookingFlowTestCase.setUp - never the real
    backend/appointments.json - and PENDING_CANCELLATION_FILE is patched
    to an isolated tmp path there too.
    """

    def _book_and_confirm(self, name="Test Patient", date="2026-12-28", time="10:00"):
        self.post_webhook(
            "Book Appointment", {"name": name, "providerId": "dr-patel", "date": date, "time": time}
        )
        booked = self.post_webhook("YesIntent").get_json()
        return booked["messages"][0]["content"]["appointment"]

    def _read_appointments(self):
        with open(self.appointments_file, 'r') as f:
            return json.load(f)

    def test_cancel_by_valid_id_full_round_trip(self):
        appointment = self._book_and_confirm()

        identify = self.post_webhook("Cancel Appointment", {"id": appointment["id"]}).get_json()
        self.assertIn("yes or no", identify["messages"][0]["content"]["text"])
        self.assertEqual(identify["context"]["cancellationStage"], "confirm")
        self.assertTrue(os.path.exists(self.pending_cancellation_file))

        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been cancelled", confirmed["messages"][0]["content"]["text"])
        self.assertEqual(confirmed["context"]["cancellationStage"], "cancelled")

        saved = self._read_appointments()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["status"], "cancelled")
        self.assertEqual(saved[0]["id"], appointment["id"])
        self.assertEqual(saved[0]["name"], "Test Patient")
        self.assertEqual(saved[0]["providerId"], "dr-patel")
        self.assertEqual(saved[0]["date"], "2026-12-28")
        self.assertEqual(saved[0]["time"], "10:00")
        self.assertFalse(os.path.exists(self.pending_cancellation_file))

    def test_cancellation_requires_confirmation_before_any_change(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Cancel Appointment", {"id": appointment["id"]})

        saved = self._read_appointments()
        self.assertNotIn("status", saved[0])

    def test_no_leaves_appointment_unchanged_and_clears_pending(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Cancel Appointment", {"id": appointment["id"]})

        response = self.post_webhook("NoIntent").get_json()
        self.assertIn("unchanged", response["messages"][0]["content"]["text"].lower())

        saved = self._read_appointments()
        self.assertNotIn("status", saved[0])
        self.assertFalse(os.path.exists(self.pending_cancellation_file))

    def test_invalid_id_does_not_fall_back_to_another_appointment(self):
        self._book_and_confirm(name="Test Patient", date="2026-12-28", time="10:00")

        response = self.post_webhook(
            "Cancel Appointment", {"id": "does-not-exist", "name": "Test Patient"}
        ).get_json()
        self.assertIn(
            "couldn't find an active appointment", response["messages"][0]["content"]["text"].lower()
        )
        self.assertFalse(os.path.exists(self.pending_cancellation_file))

        saved = self._read_appointments()
        self.assertNotIn("status", saved[0])

    def test_cancel_by_unique_name_remains_backward_compatible(self):
        appointment = self._book_and_confirm(name="Only Match")

        identify = self.post_webhook("Cancel Appointment", {"name": "Only Match"}).get_json()
        self.assertIn("yes or no", identify["messages"][0]["content"]["text"])

        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been cancelled", confirmed["messages"][0]["content"]["text"])

        saved = self._read_appointments()
        self.assertEqual(saved[0]["status"], "cancelled")
        self.assertEqual(saved[0]["id"], appointment["id"])

    def test_legacy_no_id_appointment_cancellable_by_unique_name_and_not_backfilled(self):
        with open(self.appointments_file, 'w') as f:
            json.dump([{"name": "Legacy Patient", "date": "2026-01-01", "time": "09:00"}], f)

        identify = self.post_webhook("Cancel Appointment", {"name": "Legacy Patient"}).get_json()
        self.assertIn("yes or no", identify["messages"][0]["content"]["text"])

        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been cancelled", confirmed["messages"][0]["content"]["text"])

        saved = self._read_appointments()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["status"], "cancelled")
        self.assertNotIn("id", saved[0])

    def test_duplicate_name_produces_disambiguation_and_cancels_neither(self):
        first = self._book_and_confirm(name="Dup Patient", date="2026-12-28", time="10:00")
        second = self._book_and_confirm(name="Dup Patient", date="2026-12-28", time="10:30")

        response = self.post_webhook("Cancel Appointment", {"name": "Dup Patient"}).get_json()
        text = response["messages"][0]["content"]["text"]
        self.assertIn(first["id"], text)
        self.assertIn(second["id"], text)
        self.assertEqual(response["context"]["cancellationStage"], "identifier")
        self.assertFalse(os.path.exists(self.pending_cancellation_file))

        saved = self._read_appointments()
        for a in saved:
            self.assertNotIn("status", a)

    def test_duplicate_name_disambiguation_includes_suggestions_with_ids(self):
        first = self._book_and_confirm(name="Dup Patient", date="2026-12-28", time="10:00")
        second = self._book_and_confirm(name="Dup Patient", date="2026-12-28", time="10:30")

        response = self.post_webhook("Cancel Appointment", {"name": "Dup Patient"}).get_json()
        suggestion_values = [s["value"] for s in response["messages"][0]["suggestions"]]
        self.assertIn(first["id"], suggestion_values)
        self.assertIn(second["id"], suggestion_values)

    def test_duplicate_name_with_one_legacy_record_does_not_offer_id_disambiguation(self):
        self._book_and_confirm(name="Mixed Patient", date="2026-12-28", time="10:00")
        saved = self._read_appointments()
        saved.append({"name": "Mixed Patient", "date": "2026-01-01", "time": "09:00"})
        with open(self.appointments_file, 'w') as f:
            json.dump(saved, f)

        response = self.post_webhook("Cancel Appointment", {"name": "Mixed Patient"}).get_json()
        text = response["messages"][0]["content"]["text"]
        self.assertIn("can't safely tell them apart", text)
        self.assertEqual(response["messages"][0]["suggestions"], [])
        self.assertFalse(os.path.exists(self.pending_cancellation_file))

        saved_after = self._read_appointments()
        for a in saved_after:
            self.assertNotIn("status", a)

    def test_cancelled_appointments_excluded_from_active_view(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Cancel Appointment", {"id": appointment["id"]})
        self.post_webhook("YesIntent")

        response = self.post_webhook("View Appointments").get_json()
        text = response["messages"][0]["content"]["text"]
        self.assertIn("don't have any appointments", text.lower())

    def test_legacy_no_status_appointment_remains_visible(self):
        with open(self.appointments_file, 'w') as f:
            json.dump([{"name": "Legacy Patient", "date": "2026-01-01", "time": "09:00"}], f)

        response = self.post_webhook("View Appointments").get_json()
        text = response["messages"][0]["content"]["text"]
        self.assertIn("Legacy Patient", text)

    def test_active_appointment_displays_its_id(self):
        appointment = self._book_and_confirm()

        response = self.post_webhook("View Appointments").get_json()
        text = response["messages"][0]["content"]["text"]
        self.assertIn(appointment["id"], text)

    def test_already_cancelled_before_confirmation_does_not_affect_another_appointment(self):
        first = self._book_and_confirm(name="First Patient", date="2026-12-28", time="10:00")
        second = self._book_and_confirm(name="Second Patient", date="2026-12-28", time="10:30")

        self.post_webhook("Cancel Appointment", {"id": first["id"]})

        # `first` is cancelled through some other path before the
        # confirmation reply arrives - the final "yes" must re-read fresh
        # data and detect this, rather than trusting the initial snapshot.
        saved = self._read_appointments()
        for a in saved:
            if a["id"] == first["id"]:
                a["status"] = "cancelled"
        with open(self.appointments_file, 'w') as f:
            json.dump(saved, f)

        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("no longer available to cancel", confirmed["messages"][0]["content"]["text"])

        saved_after = self._read_appointments()
        second_after = next(a for a in saved_after if a["id"] == second["id"])
        self.assertNotIn("status", second_after)

    def test_pending_cancellation_cleared_after_success(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Cancel Appointment", {"id": appointment["id"]})
        self.assertTrue(os.path.exists(self.pending_cancellation_file))

        self.post_webhook("YesIntent")
        self.assertFalse(os.path.exists(self.pending_cancellation_file))

    def test_pending_cancellation_refuses_a_new_booking_and_remains_unaffected(self):
        first = self._book_and_confirm(name="First Patient", date="2026-12-28", time="10:00")
        self.post_webhook("Cancel Appointment", {"id": first["id"]})
        self.assertTrue(os.path.exists(self.pending_cancellation_file))
        self.assertFalse(os.path.exists(self.pending_file))

        # Next slice: a brand-new booking attempt started while the
        # cancellation is pending is now refused upfront, at creation time
        # (see _handle_book_appointment's own guard) - it never reaches
        # PENDING_FILE creation, so the two-pending-files scenario this
        # test previously exercised can no longer arise via this path.
        # The pending cancellation itself is left completely untouched.
        rejected = self.post_webhook(
            "Book Appointment", {"name": "Second Patient", "providerId": "dr-patel"}
        ).get_json()
        self.assertNotIn("bookingStage", rejected["context"])
        self.assertIn(
            "already have another appointment action", rejected["messages"][0]["content"]["text"]
        )
        self.assertFalse(os.path.exists(self.pending_file))
        self.assertTrue(os.path.exists(self.pending_cancellation_file))

        # The original pending cancellation can still be confirmed normally.
        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been cancelled", confirmed["messages"][0]["content"]["text"])
        saved = self._read_appointments()
        first_after = next(a for a in saved if a["id"] == first["id"])
        self.assertEqual(first_after["status"], "cancelled")

    def test_cancellation_refuses_to_start_when_pending_booking_exists(self):
        self.post_webhook("Book Appointment", {"name": "Booker", "providerId": "dr-patel"})
        self.post_webhook(
            "Book Appointment",
            {"name": "Booker", "providerId": "dr-patel", "date": "2026-12-28", "time": "09:00"},
        )
        self.assertTrue(os.path.exists(self.pending_file))

        response = self.post_webhook("Cancel Appointment", {"name": "Anyone"}).get_json()
        self.assertNotIn("cancellationStage", response["context"])
        self.assertIn(
            "already have another appointment action", response["messages"][0]["content"]["text"]
        )
        self.assertFalse(os.path.exists(self.pending_cancellation_file))
        self.assertTrue(os.path.exists(self.pending_file))

    def test_cancellation_refuses_to_start_when_pending_update_exists(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Update Appointment", {"id": appointment["id"], "date": "2026-12-30"})
        self.assertTrue(os.path.exists(self.pending_update_file))

        response = self.post_webhook(
            "Cancel Appointment", {"id": appointment["id"]}
        ).get_json()
        self.assertNotIn("cancellationStage", response["context"])
        self.assertIn(
            "already have another appointment action", response["messages"][0]["content"]["text"]
        )
        self.assertFalse(os.path.exists(self.pending_cancellation_file))
        self.assertTrue(os.path.exists(self.pending_update_file))

        saved = self._read_appointments()
        self.assertEqual(saved[0]["date"], "2026-12-28")

    def test_cancellation_refuses_to_start_when_pending_cancellation_already_exists(self):
        first = self._book_and_confirm(name="First", date="2026-12-28", time="09:00")
        second = self._book_and_confirm(name="Second", date="2026-12-28", time="09:30")

        self.post_webhook("Cancel Appointment", {"id": first["id"]})
        self.assertTrue(os.path.exists(self.pending_cancellation_file))
        with open(self.pending_cancellation_file, 'r') as f:
            pending_before = f.read()

        response = self.post_webhook("Cancel Appointment", {"id": second["id"]}).get_json()
        self.assertNotIn("cancellationStage", response["context"])
        self.assertIn(
            "already have another appointment action", response["messages"][0]["content"]["text"]
        )

        # The FIRST pending cancellation must survive completely unchanged -
        # the second, rejected attempt must not overwrite it.
        with open(self.pending_cancellation_file, 'r') as f:
            pending_after = f.read()
        self.assertEqual(pending_before, pending_after)

        # Neither appointment was mutated by the rejected second attempt.
        saved = self._read_appointments()
        first_after = next(a for a in saved if a["id"] == first["id"])
        second_after = next(a for a in saved if a["id"] == second["id"])
        self.assertNotEqual(first_after.get("status"), "cancelled")
        self.assertNotEqual(second_after.get("status"), "cancelled")

        # The original pending cancellation can still be confirmed normally.
        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been cancelled", confirmed["messages"][0]["content"]["text"])
        saved = self._read_appointments()
        first_after = next(a for a in saved if a["id"] == first["id"])
        self.assertEqual(first_after["status"], "cancelled")


class BookingPendingTransactionMutualExclusionTest(BookingFlowTestCase):
    """Next slice: _handle_book_appointment now refuses to start/continue
    while a DIFFERENT pending transaction (cancellation or update)
    exists, mirroring _handle_cancel_appointment's/_handle_update_appointment's
    own guards - but deliberately excludes its own PENDING_FILE from the
    check, so ordinary multi-turn booking (and re-confirming an
    already-resolved slot) keeps working exactly as before.
    """

    def _book_and_confirm(self, name="Test Patient", date="2026-12-28", time="10:00"):
        self.post_webhook(
            "Book Appointment", {"name": name, "providerId": "dr-patel", "date": date, "time": time}
        )
        booked = self.post_webhook("YesIntent").get_json()
        return booked["messages"][0]["content"]["appointment"]

    def _read_appointments(self):
        with open(self.appointments_file, 'r') as f:
            return json.load(f)

    def test_booking_refused_when_pending_cancellation_exists(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Cancel Appointment", {"id": appointment["id"]})
        self.assertTrue(os.path.exists(self.pending_cancellation_file))

        response = self.post_webhook("Book Appointment", {"name": "New Patient"}).get_json()
        self.assertNotIn("bookingStage", response["context"])
        self.assertIn(
            "already have another appointment action", response["messages"][0]["content"]["text"]
        )
        self.assertFalse(os.path.exists(self.pending_file))

    def test_booking_refused_when_pending_update_exists(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Update Appointment", {"id": appointment["id"], "date": "2026-12-30"})
        self.assertTrue(os.path.exists(self.pending_update_file))

        response = self.post_webhook("Book Appointment", {"name": "New Patient"}).get_json()
        self.assertNotIn("bookingStage", response["context"])
        self.assertIn(
            "already have another appointment action", response["messages"][0]["content"]["text"]
        )
        self.assertFalse(os.path.exists(self.pending_file))

    def test_rejected_booking_attempt_does_not_overwrite_existing_pending_cancellation(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Cancel Appointment", {"id": appointment["id"]})
        with open(self.pending_cancellation_file, 'r') as f:
            pending_before = f.read()

        self.post_webhook(
            "Book Appointment",
            {"name": "New Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "11:00"},
        )

        with open(self.pending_cancellation_file, 'r') as f:
            pending_after = f.read()
        self.assertEqual(pending_before, pending_after)
        self.assertFalse(os.path.exists(self.pending_file))

    def test_rejected_booking_attempt_does_not_mutate_appointments(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Update Appointment", {"id": appointment["id"], "date": "2026-12-30"})

        self.post_webhook(
            "Book Appointment",
            {"name": "New Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "11:00"},
        )

        saved = self._read_appointments()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["id"], appointment["id"])
        self.assertEqual(saved[0]["date"], "2026-12-28")

    def test_existing_pending_booking_continues_normally_through_remaining_stages(self):
        # Reaches the 'provider' stage - no PENDING_FILE exists yet, since
        # it's only written once name/provider/date/slot are all resolved.
        response = self.post_webhook("Book Appointment", {"name": "Continuer"}).get_json()
        self.assertEqual(response["context"]["bookingStage"], "provider")
        self.assertFalse(os.path.exists(self.pending_file))

        response = self.post_webhook(
            "Book Appointment", {"name": "Continuer", "providerId": "dr-patel"}
        ).get_json()
        self.assertEqual(response["context"]["bookingStage"], "date")

        response = self.post_webhook(
            "Book Appointment",
            {"name": "Continuer", "providerId": "dr-patel", "date": "2026-12-28"},
        ).get_json()
        self.assertEqual(response["context"]["bookingStage"], "slot")

        # This call resolves the slot and writes PENDING_FILE for the
        # first time - the guard (checking OTHER pending files only) must
        # not interfere with this, its own transaction's first write.
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Continuer", "providerId": "dr-patel", "date": "2026-12-28", "time": "09:00"},
        ).get_json()
        self.assertEqual(response["context"]["bookingStage"], "confirm")
        self.assertTrue(os.path.exists(self.pending_file))

        # Re-sending the exact same, already-resolved confirm-stage
        # parameters again (e.g. a retry) must not be blocked by its own
        # existing PENDING_FILE - it re-validates and re-confirms normally.
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Continuer", "providerId": "dr-patel", "date": "2026-12-28", "time": "09:00"},
        ).get_json()
        self.assertEqual(response["context"]["bookingStage"], "confirm")

        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been booked", confirmed["messages"][0]["content"]["text"])

    def test_normal_booking_still_works_when_nothing_else_is_pending(self):
        response = self.post_webhook(
            "Book Appointment",
            {"name": "Solo", "providerId": "dr-patel", "date": "2026-12-28", "time": "09:00"},
        ).get_json()
        self.assertEqual(response["context"]["bookingStage"], "confirm")

        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been booked", confirmed["messages"][0]["content"]["text"])
        saved = self._read_appointments()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["name"], "Solo")


if __name__ == '__main__':
    unittest.main()
