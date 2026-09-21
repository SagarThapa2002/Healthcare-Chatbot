"""Tests for Phase 6.1 Slice B: safe, confirmed, ID-preferring appointment
updates in backend/chatbot_logic.py.

Replaces the previous immediate-mutation, name-only, unconfirmed
_handle_update_appointment with an IDENTIFIER -> FIELDS -> CONFIRM ->
UPDATED flow, mirroring test_chatbot_logic_booking_availability.py's own
CancellationFlowTest in structure and conventions (kept in its own file
per the approved Slice B design, rather than growing that file further).

Every test isolates appointment/pending file I/O to a temp directory -
never the real backend/appointments.json - and uses the real, synthetic
backend/providers.json / backend/provider_availability.json data (same
fixture as the booking/cancellation tests): dr-patel is available Monday
and Wednesday, 09:00-17:00, 30-minute slots. 2026-12-28 is a Monday and
2026-12-30 is a Wednesday, used throughout so fixture dates line up with
real provider availability.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import availability_service, chatbot_logic


class UpdateFlowTestCase(unittest.TestCase):
    """Base class: isolates appointment/pending file I/O from the real
    backend/appointments.json, exactly like test_chatbot_logic_booking_availability.py's
    BookingFlowTestCase. Deliberately self-contained (no cross-file
    inheritance) so this file's discovered test count always equals the
    number of test_ methods actually defined here.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

        self.appointments_file = os.path.join(self.tmp_dir.name, 'appointments.json')
        self.pending_file = os.path.join(self.tmp_dir.name, 'pending_appointments.json')
        self.pending_cancellation_file = os.path.join(self.tmp_dir.name, 'pending_cancellation.json')
        self.pending_update_file = os.path.join(self.tmp_dir.name, 'pending_update.json')

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

    def _book_and_confirm(self, name="Test Patient", provider_id="dr-patel", date="2026-12-28", time="10:00"):
        self.post_webhook(
            "Book Appointment", {"name": name, "providerId": provider_id, "date": date, "time": time}
        )
        booked = self.post_webhook("YesIntent").get_json()
        return booked["messages"][0]["content"]["appointment"]

    def _read_appointments(self):
        with open(self.appointments_file, 'r') as f:
            return json.load(f)

    def _write_appointments(self, appointments):
        with open(self.appointments_file, 'w') as f:
            json.dump(appointments, f, indent=2)


class UpdateByIdTest(UpdateFlowTestCase):
    def test_identifier_alone_without_date_or_time_enters_fields_stage(self):
        appointment = self._book_and_confirm(date="2026-12-28", time="10:00")

        response = self.post_webhook("Update Appointment", {"id": appointment["id"]}).get_json()
        self.assertEqual(response["context"]["updateStage"], "fields")
        self.assertFalse(os.path.exists(self.pending_update_file))

        saved = self._read_appointments()
        self.assertEqual(saved[0]["date"], "2026-12-28")
        self.assertEqual(saved[0]["time"], "10:00")

    def test_yes_updates_both_date_and_time_when_both_given(self):
        appointment = self._book_and_confirm(date="2026-12-28", time="10:00")
        self.post_webhook(
            "Update Appointment", {"id": appointment["id"], "date": "2026-12-30", "time": "11:00"}
        )
        self.post_webhook("YesIntent")

        saved = self._read_appointments()
        self.assertEqual(saved[0]["date"], "2026-12-30")
        self.assertEqual(saved[0]["time"], "11:00")

    def test_update_by_valid_id_full_round_trip(self):
        appointment = self._book_and_confirm()

        identify = self.post_webhook(
            "Update Appointment", {"id": appointment["id"], "date": "2026-12-30"}
        ).get_json()
        self.assertIn("yes or no", identify["messages"][0]["content"]["text"])
        self.assertEqual(identify["context"]["updateStage"], "confirm")
        self.assertTrue(os.path.exists(self.pending_update_file))

        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been updated", confirmed["messages"][0]["content"]["text"])
        self.assertEqual(confirmed["context"]["updateStage"], "updated")
        self.assertFalse(os.path.exists(self.pending_update_file))

        saved = self._read_appointments()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["id"], appointment["id"])
        self.assertEqual(saved[0]["date"], "2026-12-30")
        self.assertEqual(saved[0]["time"], "10:00")

    def test_invalid_id_does_not_fall_back_to_name(self):
        appointment = self._book_and_confirm(name="Real Patient")

        response = self.post_webhook(
            "Update Appointment", {"id": "not-a-real-id", "name": "Real Patient", "date": "2026-12-30"}
        ).get_json()
        self.assertIn("couldn't find an active appointment with that id", response["messages"][0]["content"]["text"].lower())
        self.assertEqual(response["context"]["updateStage"], "identifier")
        self.assertFalse(os.path.exists(self.pending_update_file))

        saved = self._read_appointments()
        self.assertEqual(saved[0]["date"], appointment["date"])

    def test_cancelled_appointment_cannot_be_updated_by_id(self):
        appointment = self._book_and_confirm()
        appointments = self._read_appointments()
        appointments[0]["status"] = "cancelled"
        self._write_appointments(appointments)

        response = self.post_webhook(
            "Update Appointment", {"id": appointment["id"], "date": "2026-12-30"}
        ).get_json()
        self.assertIn("couldn't find an active appointment", response["messages"][0]["content"]["text"].lower())
        self.assertFalse(os.path.exists(self.pending_update_file))

        saved = self._read_appointments()
        self.assertEqual(saved[0]["status"], "cancelled")
        self.assertEqual(saved[0]["date"], appointment["date"])


class UpdateByNameTest(UpdateFlowTestCase):
    def test_unique_name_update(self):
        self._book_and_confirm(name="Unique Patient", time="10:00")

        identify = self.post_webhook(
            "Update Appointment", {"name": "Unique Patient", "time": "11:00"}
        ).get_json()
        self.assertIn("yes or no", identify["messages"][0]["content"]["text"])
        self.assertEqual(identify["context"]["updateStage"], "confirm")

        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been updated", confirmed["messages"][0]["content"]["text"])

        saved = self._read_appointments()
        self.assertEqual(saved[0]["time"], "11:00")
        self.assertEqual(saved[0]["date"], "2026-12-28")

    def test_unmatched_name_reports_not_found(self):
        self._book_and_confirm(name="Someone")

        response = self.post_webhook(
            "Update Appointment", {"name": "Nobody Here", "date": "2026-12-30"}
        ).get_json()
        self.assertIn("couldn't find an appointment for nobody here", response["messages"][0]["content"]["text"].lower())
        self.assertNotIn("updateStage", response["context"])

    def test_cancelled_appointment_cannot_be_updated_by_name_and_is_not_reactivated(self):
        self._book_and_confirm(name="Cancelled Patient")
        appointments = self._read_appointments()
        appointments[0]["status"] = "cancelled"
        self._write_appointments(appointments)

        response = self.post_webhook(
            "Update Appointment", {"name": "Cancelled Patient", "date": "2026-12-30"}
        ).get_json()
        self.assertIn("couldn't find an appointment for cancelled patient", response["messages"][0]["content"]["text"].lower())

        saved = self._read_appointments()
        self.assertEqual(saved[0]["status"], "cancelled")
        self.assertEqual(saved[0]["date"], "2026-12-28")

    def test_duplicate_name_disambiguation_lists_ids_and_does_not_mutate(self):
        first = self._book_and_confirm(name="Dup Patient", date="2026-12-28", time="09:00")
        second = self._book_and_confirm(name="Dup Patient", date="2026-12-28", time="09:30")

        response = self.post_webhook(
            "Update Appointment", {"name": "Dup Patient", "date": "2026-12-30"}
        ).get_json()
        text = response["messages"][0]["content"]["text"]
        self.assertIn("multiple appointments", text.lower())
        self.assertIn(first["id"], text)
        self.assertIn(second["id"], text)
        self.assertEqual(response["context"]["updateStage"], "identifier")
        self.assertFalse(os.path.exists(self.pending_update_file))

        saved = self._read_appointments()
        for appointment in saved:
            self.assertEqual(appointment["date"], "2026-12-28")
            self.assertNotIn("status", appointment)

    def test_legacy_unique_name_update(self):
        self._write_appointments([
            {"name": "Legacy Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        ])

        identify = self.post_webhook(
            "Update Appointment", {"name": "Legacy Patient", "date": "2026-12-30"}
        ).get_json()
        self.assertEqual(identify["context"]["updateStage"], "confirm")

        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been updated", confirmed["messages"][0]["content"]["text"])

        saved = self._read_appointments()
        self.assertEqual(len(saved), 1)
        self.assertNotIn("id", saved[0])
        self.assertEqual(saved[0]["date"], "2026-12-30")
        self.assertEqual(saved[0]["name"], "Legacy Patient")

    def test_ambiguous_group_containing_legacy_record_fails_safely(self):
        self._write_appointments([
            {"name": "Legacy Dup", "providerId": "dr-patel", "date": "2026-12-28", "time": "09:00"},
            {"name": "Legacy Dup", "providerId": "dr-patel", "date": "2026-12-28", "time": "09:30", "id": "real-id-1"},
        ])

        response = self.post_webhook(
            "Update Appointment", {"name": "Legacy Dup", "date": "2026-12-30"}
        ).get_json()
        text = response["messages"][0]["content"]["text"].lower()
        self.assertIn("doesn't have a reference id", text)
        self.assertIn("none have been changed", text)
        self.assertEqual(response["context"]["updateStage"], "identifier")
        self.assertFalse(os.path.exists(self.pending_update_file))

        saved = self._read_appointments()
        for appointment in saved:
            self.assertEqual(appointment["date"], "2026-12-28")


class UpdateAvailabilityValidationTest(UpdateFlowTestCase):
    def test_invalid_date_is_rejected_and_stays_in_fields_stage(self):
        appointment = self._book_and_confirm()

        response = self.post_webhook(
            "Update Appointment", {"id": appointment["id"], "date": "not-a-date"}
        ).get_json()
        self.assertEqual(response["context"]["updateStage"], "fields")
        self.assertFalse(os.path.exists(self.pending_update_file))

        saved = self._read_appointments()
        self.assertEqual(saved[0]["date"], "2026-12-28")

    def test_invalid_time_is_rejected_and_stays_in_fields_stage(self):
        appointment = self._book_and_confirm()

        response = self.post_webhook(
            "Update Appointment", {"id": appointment["id"], "time": "99:99"}
        ).get_json()
        self.assertEqual(response["context"]["updateStage"], "fields")
        self.assertFalse(os.path.exists(self.pending_update_file))

    def test_availability_conflict_with_another_appointment_is_rejected(self):
        appointment = self._book_and_confirm(name="Mover", date="2026-12-28", time="09:00")
        self._book_and_confirm(name="Occupant", date="2026-12-28", time="09:30")

        response = self.post_webhook(
            "Update Appointment", {"id": appointment["id"], "time": "09:30"}
        ).get_json()
        self.assertIn("isn't available", response["messages"][0]["content"]["text"])
        self.assertEqual(response["context"]["updateStage"], "fields")
        self.assertFalse(os.path.exists(self.pending_update_file))

        saved = self._read_appointments()
        mover = next(a for a in saved if a["id"] == appointment["id"])
        self.assertEqual(mover["time"], "09:00")

    def test_unchanged_current_slot_does_not_conflict_with_itself(self):
        appointment = self._book_and_confirm(date="2026-12-28", time="09:00")

        response = self.post_webhook(
            "Update Appointment", {"id": appointment["id"], "date": "2026-12-28", "time": "09:00"}
        ).get_json()
        self.assertEqual(response["context"]["updateStage"], "confirm")
        self.assertIn("yes or no", response["messages"][0]["content"]["text"])

    def test_legacy_record_with_no_provider_id_skips_availability_check(self):
        self._write_appointments([
            {"name": "No Provider", "date": "2026-12-28", "time": "10:00"},
        ])

        response = self.post_webhook(
            "Update Appointment", {"name": "No Provider", "date": "not-a-real-date-but-allowed"}
        ).get_json()
        # No providerId means there's nothing to validate against - the
        # proposed change is accepted straight to confirmation, matching
        # availability_service.py's own documented "never a conflict for a
        # provider-specific query" convention for a missing providerId.
        self.assertEqual(response["context"]["updateStage"], "confirm")


class UpdateConfirmationTest(UpdateFlowTestCase):
    def test_confirmation_required_before_any_mutation(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Update Appointment", {"id": appointment["id"], "date": "2026-12-30"})

        saved = self._read_appointments()
        self.assertEqual(saved[0]["date"], "2026-12-28")

    def test_no_leaves_appointment_unchanged_and_clears_pending(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Update Appointment", {"id": appointment["id"], "date": "2026-12-30"})

        response = self.post_webhook("NoIntent").get_json()
        self.assertIn("unchanged", response["messages"][0]["content"]["text"].lower())
        self.assertFalse(os.path.exists(self.pending_update_file))

        saved = self._read_appointments()
        self.assertEqual(saved[0]["date"], "2026-12-28")

    def test_yes_updates_only_date_when_only_date_given(self):
        appointment = self._book_and_confirm(date="2026-12-28", time="10:00")
        self.post_webhook("Update Appointment", {"id": appointment["id"], "date": "2026-12-30"})
        self.post_webhook("YesIntent")

        saved = self._read_appointments()
        self.assertEqual(saved[0]["date"], "2026-12-30")
        self.assertEqual(saved[0]["time"], "10:00")

    def test_yes_updates_only_time_when_only_time_given(self):
        appointment = self._book_and_confirm(date="2026-12-28", time="10:00")
        self.post_webhook("Update Appointment", {"id": appointment["id"], "time": "11:00"})
        self.post_webhook("YesIntent")

        saved = self._read_appointments()
        self.assertEqual(saved[0]["date"], "2026-12-28")
        self.assertEqual(saved[0]["time"], "11:00")

    def test_id_name_provider_duration_status_are_preserved(self):
        self._book_and_confirm(name="Preserve Me", provider_id="dr-patel", date="2026-12-28", time="10:00")
        appointments = self._read_appointments()
        appointments[0]["durationMinutes"] = 45
        self._write_appointments(appointments)
        original = appointments[0]

        self.post_webhook("Update Appointment", {"id": original["id"], "date": "2026-12-30"})
        self.post_webhook("YesIntent")

        saved = self._read_appointments()
        self.assertEqual(saved[0]["id"], original["id"])
        self.assertEqual(saved[0]["name"], "Preserve Me")
        self.assertEqual(saved[0]["providerId"], "dr-patel")
        self.assertEqual(saved[0]["durationMinutes"], 45)
        self.assertNotIn("status", saved[0])
        self.assertEqual(saved[0]["date"], "2026-12-30")


class UpdateFinalConfirmationSafetyTest(UpdateFlowTestCase):
    """Mirrors CancellationFlowTest's own "never trust the initial
    snapshot" safety tests, adapted for update.
    """

    def test_final_confirmation_rereads_fresh_state(self):
        appointment = self._book_and_confirm(date="2026-12-28", time="10:00")
        self.post_webhook("Update Appointment", {"id": appointment["id"], "time": "11:00"})

        # Out-of-band change between identify and confirm: someone else
        # updated an unrelated field on the same record directly.
        appointments = self._read_appointments()
        appointments[0]["providerId"] = "dr-patel"
        self._write_appointments(appointments)

        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been updated", confirmed["messages"][0]["content"]["text"])
        saved = self._read_appointments()
        self.assertEqual(saved[0]["time"], "11:00")

    def test_target_cancelled_between_selection_and_confirmation_is_refused(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Update Appointment", {"id": appointment["id"], "date": "2026-12-30"})

        appointments = self._read_appointments()
        appointments[0]["status"] = "cancelled"
        self._write_appointments(appointments)

        response = self.post_webhook("YesIntent").get_json()
        self.assertIn("no longer available to update", response["messages"][0]["content"]["text"])
        self.assertFalse(os.path.exists(self.pending_update_file))

        saved = self._read_appointments()
        self.assertEqual(saved[0]["status"], "cancelled")
        self.assertEqual(saved[0]["date"], "2026-12-28")

    def test_target_removed_between_selection_and_confirmation_is_refused(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Update Appointment", {"id": appointment["id"], "date": "2026-12-30"})

        self._write_appointments([])

        response = self.post_webhook("YesIntent").get_json()
        self.assertIn("no longer available to update", response["messages"][0]["content"]["text"])
        self.assertFalse(os.path.exists(self.pending_update_file))

    def test_conflict_introduced_between_selection_and_confirmation_is_refused(self):
        appointment = self._book_and_confirm(name="Mover", date="2026-12-28", time="09:00")
        self.post_webhook("Update Appointment", {"id": appointment["id"], "time": "09:30"})

        appointments = self._read_appointments()
        appointments.append(
            {"name": "Late Arrival", "providerId": "dr-patel", "date": "2026-12-28", "time": "09:30", "id": "late-1"}
        )
        self._write_appointments(appointments)

        response = self.post_webhook("YesIntent").get_json()
        self.assertIn("no longer available", response["messages"][0]["content"]["text"])
        self.assertFalse(os.path.exists(self.pending_update_file))

        saved = self._read_appointments()
        mover = next(a for a in saved if a["id"] == appointment["id"])
        self.assertEqual(mover["time"], "09:00")

    def test_final_confirmation_by_id_never_touches_a_same_named_appointment(self):
        first = self._book_and_confirm(name="Dup Patient", date="2026-12-28", time="09:00")
        second = self._book_and_confirm(name="Dup Patient", date="2026-12-28", time="09:30")

        self.post_webhook("Update Appointment", {"id": second["id"], "date": "2026-12-30"})
        self.post_webhook("YesIntent")

        saved = self._read_appointments()
        first_after = next(a for a in saved if a["id"] == first["id"])
        second_after = next(a for a in saved if a["id"] == second["id"])
        self.assertEqual(first_after["date"], "2026-12-28")
        self.assertEqual(second_after["date"], "2026-12-30")

    def test_legacy_final_confirmation_matches_original_triple_not_first_matching_name(self):
        self._write_appointments([
            {"name": "Legacy Solo", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        ])
        self.post_webhook("Update Appointment", {"name": "Legacy Solo", "date": "2026-12-30"})

        # A second, same-named legacy record appears between selection and
        # confirmation - the pending record's captured (name, originalDate,
        # originalTime) triple must still identify only the original one.
        appointments = self._read_appointments()
        appointments.append(
            {"name": "Legacy Solo", "providerId": "dr-patel", "date": "2026-12-28", "time": "11:00"}
        )
        self._write_appointments(appointments)

        self.post_webhook("YesIntent")

        saved = self._read_appointments()
        original = next(a for a in saved if a["time"] == "10:00" or a["date"] == "2026-12-30")
        untouched = next(a for a in saved if a["time"] == "11:00")
        self.assertEqual(original["date"], "2026-12-30")
        self.assertEqual(untouched["date"], "2026-12-28")


class UpdatePendingTransactionMutualExclusionTest(UpdateFlowTestCase):
    def test_update_refuses_to_start_when_pending_booking_exists(self):
        self.post_webhook("Book Appointment", {"name": "Booker", "providerId": "dr-patel"})
        self.post_webhook(
            "Book Appointment",
            {"name": "Booker", "providerId": "dr-patel", "date": "2026-12-28", "time": "09:00"},
        )
        self.assertTrue(os.path.exists(self.pending_file))

        response = self.post_webhook("Update Appointment", {"name": "Anyone", "date": "2026-12-30"}).get_json()
        self.assertNotIn("updateStage", response["context"])
        self.assertFalse(os.path.exists(self.pending_update_file))
        self.assertTrue(os.path.exists(self.pending_file))

    def test_update_refuses_to_start_when_pending_cancellation_exists(self):
        appointment = self._book_and_confirm()
        self.post_webhook("Cancel Appointment", {"id": appointment["id"]})
        self.assertTrue(os.path.exists(self.pending_cancellation_file))

        response = self.post_webhook(
            "Update Appointment", {"id": appointment["id"], "date": "2026-12-30"}
        ).get_json()
        self.assertNotIn("updateStage", response["context"])
        self.assertFalse(os.path.exists(self.pending_update_file))
        self.assertTrue(os.path.exists(self.pending_cancellation_file))

    def test_update_refuses_to_start_when_pending_update_already_exists(self):
        first = self._book_and_confirm(name="First", date="2026-12-28", time="09:00")
        second = self._book_and_confirm(name="Second", date="2026-12-28", time="09:30")

        self.post_webhook("Update Appointment", {"id": first["id"], "date": "2026-12-30"})
        self.assertTrue(os.path.exists(self.pending_update_file))
        with open(self.pending_update_file, 'r') as f:
            pending_before = f.read()

        response = self.post_webhook(
            "Update Appointment", {"id": second["id"], "time": "10:00"}
        ).get_json()
        self.assertNotIn("updateStage", response["context"])
        self.assertIn(
            "already have another appointment action", response["messages"][0]["content"]["text"]
        )

        # The FIRST pending update must survive completely unchanged - the
        # second, rejected attempt must not overwrite it.
        with open(self.pending_update_file, 'r') as f:
            pending_after = f.read()
        self.assertEqual(pending_before, pending_after)

        # Neither appointment was mutated by the rejected second attempt.
        saved = self._read_appointments()
        first_after = next(a for a in saved if a["id"] == first["id"])
        second_after = next(a for a in saved if a["id"] == second["id"])
        self.assertEqual(first_after["date"], "2026-12-28")
        self.assertEqual(second_after["date"], "2026-12-28")
        self.assertEqual(second_after["time"], "09:30")

        # The original pending update can still be confirmed normally.
        confirmed = self.post_webhook("YesIntent").get_json()
        self.assertIn("has been updated", confirmed["messages"][0]["content"]["text"])
        saved = self._read_appointments()
        first_after = next(a for a in saved if a["id"] == first["id"])
        self.assertEqual(first_after["date"], "2026-12-30")

    def test_multiple_pending_transaction_files_fail_closed_on_yes(self):
        appointment = self._book_and_confirm(name="First", date="2026-12-28", time="09:00")
        self.post_webhook("Cancel Appointment", {"id": appointment["id"]})
        self.assertTrue(os.path.exists(self.pending_cancellation_file))

        # Simulate a second, leaked pending booking file existing at the
        # same time (not reachable through this slice's own guard, which
        # prevents *creating* an update while another is pending - but
        # handle_webhook_request's dispatch must still fail closed if it
        # ever happens, e.g. from a bug or manual file state).
        with open(self.pending_file, 'w') as f:
            json.dump({"name": "Someone", "providerId": "dr-patel", "date": "2026-12-28", "time": "11:00"}, f)

        response = self.post_webhook("YesIntent").get_json()
        self.assertNotIn("cancellationStage", response["context"])
        self.assertNotIn("bookingStage", response["context"])
        self.assertNotIn("updateStage", response["context"])
        self.assertIn("more than one action", response["messages"][0]["content"]["text"].lower())
        self.assertTrue(os.path.exists(self.pending_file))
        self.assertTrue(os.path.exists(self.pending_cancellation_file))

        saved = self._read_appointments()
        self.assertNotEqual(saved[0].get("status"), "cancelled")

    def test_multiple_pending_transaction_files_fail_closed_on_no(self):
        appointment = self._book_and_confirm(name="First", date="2026-12-28", time="09:00")
        self.post_webhook("Cancel Appointment", {"id": appointment["id"]})
        with open(self.pending_file, 'w') as f:
            json.dump({"name": "Someone", "providerId": "dr-patel", "date": "2026-12-28", "time": "11:00"}, f)

        response = self.post_webhook("NoIntent").get_json()
        self.assertIn("more than one action", response["messages"][0]["content"]["text"].lower())
        self.assertTrue(os.path.exists(self.pending_file))
        self.assertTrue(os.path.exists(self.pending_cancellation_file))


class UpdateStageContextTest(UpdateFlowTestCase):
    def test_non_update_intents_never_carry_an_update_stage(self):
        appointment = self._book_and_confirm()
        for intent, params in [
            ("General FAQ", {}),
            ("Symptom Check", {"symptom": "a headache"}),
            ("Cancel Appointment", {"name": "Nobody"}),
            ("View Appointments", {}),
        ]:
            with self.subTest(intent=intent):
                response = self.post_webhook(intent, params).get_json()
                self.assertNotIn("updateStage", response["context"])

        response = self.post_webhook("Book Appointment", {"name": "Someone Else"}).get_json()
        self.assertNotIn("updateStage", response["context"])


if __name__ == '__main__':
    unittest.main()
