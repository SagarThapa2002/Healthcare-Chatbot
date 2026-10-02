"""Tests that cancellation/update messages show a provider's name (resolved
through provider_repository) instead of its raw id, while every internal
identifier - stored providerId, pending state, suggestion values - stays
the provider/appointment id.

All data files are redirected to a temp directory; the real backend/*.json
files are never read or written.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import availability_service, chatbot_logic, provider_repository, reminder_service

# Every request in this file is sent with this browser owner token, so the
# appointments these tests book are owned by - and visible to - that owner
# (appointment access is owner-scoped; see backend/tests/test_owner_token.py).
TEST_OWNER = "7e570000-0000-4000-8000-000000000001"

ID_A = "11111111-1111-4111-8111-111111111111"
ID_B = "22222222-2222-4222-8222-222222222222"


def appointment(appointment_id, provider_id="dr-patel", time="10:00", name="Test Patient"):
    # A record with an id is a current-format record booked by TEST_OWNER; one
    # without (legacy) has no owner either, so no one can reach it.
    record = {"name": name, "date": "2026-12-28", "time": time}
    if appointment_id:
        record["id"] = appointment_id
        record["ownerId"] = TEST_OWNER
    if provider_id:
        record["providerId"] = provider_id
    return record


class ProviderDisplayNameTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        tmp = self.tmp_dir.name
        self.files = {
            'appointments': os.path.join(tmp, 'appointments.json'),
            'pending': os.path.join(tmp, 'pending_appointments.json'),
            'pending_update': os.path.join(tmp, 'pending_update.json'),
            'pending_cancellation': os.path.join(tmp, 'pending_cancellation.json'),
            'reminders': os.path.join(tmp, 'reminders.json'),
        }
        patches = [
            patch.object(chatbot_logic, 'APPOINTMENTS_FILE', self.files['appointments']),
            patch.object(chatbot_logic, 'PENDING_FILE', self.files['pending']),
            patch.object(chatbot_logic, 'PENDING_UPDATE_FILE', self.files['pending_update']),
            patch.object(chatbot_logic, 'PENDING_CANCELLATION_FILE', self.files['pending_cancellation']),
            patch.object(availability_service, 'APPOINTMENTS_FILE', self.files['appointments']),
            patch.object(reminder_service, 'APPOINTMENTS_FILE', self.files['appointments']),
            patch.object(reminder_service, 'REMINDERS_FILE', self.files['reminders']),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.test_client()
        self.client.environ_base['HTTP_X_OWNER_TOKEN'] = TEST_OWNER

    def seed(self, *records):
        with open(self.files['appointments'], 'w') as f:
            json.dump(list(records), f)

    def read(self, key):
        with open(self.files[key]) as f:
            return json.load(f)

    def post(self, intent, parameters=None):
        body = {"queryResult": {"intent": {"displayName": intent}, "parameters": parameters or {}}}
        return self.client.post('/webhook/webhook', json=body).get_json()

    def text(self, response):
        return response["messages"][0]["content"]["text"]

    # --- known providers ---

    def test_cancellation_confirmation_shows_the_provider_name(self):
        self.seed(appointment(ID_A))
        response = self.post("Cancel Appointment", {"id": ID_A})
        self.assertEqual(response["context"]["cancellationStage"], "confirm")
        self.assertEqual(
            self.text(response),
            "Please confirm — cancel the appointment for Test Patient on 2026-12-28 "
            "at 10:00 with Dr. Patel? (yes or no)",
        )

    def test_cancellation_disambiguation_list_shows_provider_names(self):
        self.seed(appointment(ID_A, "dr-patel", "10:00"), appointment(ID_B, "dr-nguyen", "11:00"))
        response = self.post("Cancel Appointment", {"name": "Test Patient"})
        self.assertEqual(response["context"]["cancellationStage"], "identifier")
        text = self.text(response)
        self.assertIn(f"- ID {ID_A}, 2026-12-28 at 10:00, provider Dr. Patel", text)
        self.assertIn(f"- ID {ID_B}, 2026-12-28 at 11:00, provider Dr. Nguyen", text)
        self.assertNotIn("dr-patel", text)
        self.assertNotIn("dr-nguyen", text)
        # Chip values are still the appointment ids.
        self.assertEqual([s["value"] for s in response["messages"][0]["suggestions"]], [ID_A, ID_B])

    def test_update_disambiguation_list_shows_provider_names(self):
        self.seed(appointment(ID_A, "dr-patel", "10:00"), appointment(ID_B, "dr-okafor", "11:00"))
        response = self.post("Update Appointment", {"name": "Test Patient"})
        self.assertEqual(response["context"]["updateStage"], "identifier")
        text = self.text(response)
        self.assertIn(f"- ID {ID_A}, 2026-12-28 at 10:00, provider Dr. Patel", text)
        self.assertIn(f"- ID {ID_B}, 2026-12-28 at 11:00, provider Dr. Okafor", text)
        self.assertNotIn("dr-", text)
        self.assertEqual([s["value"] for s in response["messages"][0]["suggestions"]], [ID_A, ID_B])

    # --- fallbacks ---

    def test_unknown_provider_id_falls_back_to_the_raw_id(self):
        self.seed(appointment(ID_A, "dr-retired", "10:00"), appointment(ID_B, "dr-patel", "11:00"))

        listing = self.post("Cancel Appointment", {"name": "Test Patient"})
        self.assertIn(f"- ID {ID_A}, 2026-12-28 at 10:00, provider dr-retired", self.text(listing))
        self.assertIn(f"- ID {ID_B}, 2026-12-28 at 11:00, provider Dr. Patel", self.text(listing))

        confirm = self.post("Cancel Appointment", {"id": ID_A})
        self.assertEqual(confirm["context"]["cancellationStage"], "confirm")
        self.assertIn("at 10:00 with dr-retired? (yes or no)", self.text(confirm))
        self.assertEqual(self.read('pending_cancellation'), {"id": ID_A})

    def test_provider_data_error_falls_back_to_the_raw_id_without_breaking_the_flow(self):
        self.seed(appointment(ID_A))
        error = provider_repository.ProviderDataError("providers file not found: /secret/path/providers.json")
        with patch.object(provider_repository, 'find_provider', side_effect=error):
            with self.assertLogs('backend.chatbot_logic', level='WARNING') as logs:
                response = self.post("Cancel Appointment", {"id": ID_A})

        self.assertTrue(response["success"])
        self.assertEqual(response["context"]["cancellationStage"], "confirm")
        self.assertIn("at 10:00 with dr-patel? (yes or no)", self.text(response))
        self.assertEqual(self.read('pending_cancellation'), {"id": ID_A})
        self.assertEqual(
            logs.output,
            ["WARNING:backend.chatbot_logic:provider display-name lookup failed "
             "provider_id=dr-patel exception_type=ProviderDataError"],
        )

    def test_provider_data_error_in_a_disambiguation_list_falls_back_to_raw_ids(self):
        self.seed(appointment(ID_A, "dr-patel", "10:00"), appointment(ID_B, "dr-nguyen", "11:00"))
        error = provider_repository.ProviderDataError("corrupt")
        with patch.object(provider_repository, 'find_provider', side_effect=error):
            with self.assertLogs('backend.chatbot_logic', level='WARNING'):
                response = self.post("Update Appointment", {"name": "Test Patient"})
        self.assertEqual(response["context"]["updateStage"], "identifier")
        self.assertIn(f"- ID {ID_A}, 2026-12-28 at 10:00, provider dr-patel", self.text(response))
        self.assertIn(f"- ID {ID_B}, 2026-12-28 at 11:00, provider dr-nguyen", self.text(response))

    # --- identifiers and legacy records unchanged ---

    def test_internal_identifiers_are_unchanged_through_a_full_cancellation(self):
        self.seed(appointment(ID_A))
        self.post("Cancel Appointment", {"id": ID_A})
        self.assertEqual(self.read('pending_cancellation'), {"id": ID_A})

        cancelled = self.post("YesIntent")
        self.assertEqual(cancelled["context"]["cancellationStage"], "cancelled")
        saved = self.read('appointments')
        self.assertEqual(saved[0]["providerId"], "dr-patel")
        self.assertEqual(saved[0]["status"], "cancelled")

    def test_update_pending_state_keeps_the_appointment_id(self):
        self.seed(appointment(ID_A))
        response = self.post("Update Appointment", {"id": ID_A, "date": "2026-12-30", "time": "11:00"})
        self.assertEqual(response["context"]["updateStage"], "confirm")
        pending = self.read('pending_update')
        self.assertEqual(pending["id"], ID_A)
        self.assertNotIn("Dr. Patel", json.dumps(pending))
        self.assertEqual(self.read('appointments')[0]["providerId"], "dr-patel")

    def test_record_without_provider_id_keeps_its_current_wording(self):
        self.seed(appointment(ID_A, provider_id=None))
        with patch.object(provider_repository, 'find_provider') as spy:
            response = self.post("Cancel Appointment", {"id": ID_A})
        spy.assert_not_called()
        self.assertEqual(
            self.text(response),
            "Please confirm — cancel the appointment for Test Patient on 2026-12-28 at 10:00? (yes or no)",
        )

    def test_legacy_records_without_an_owner_are_not_listed_for_cancellation(self):
        # Legacy records (no id, no ownerId) belong to no owner, so a name
        # lookup does not find them - and nothing about them is shown.
        self.seed(appointment(None, provider_id=None, time="10:00"),
                  appointment(None, provider_id=None, time="11:00"))
        response = self.post("Cancel Appointment", {"name": "Test Patient"})
        self.assertNotIn("cancellationStage", response["context"])
        self.assertEqual(self.text(response), "I couldn't find an appointment for Test Patient to cancel.")
        self.assertFalse(os.path.exists(self.files['pending_cancellation']))


if __name__ == '__main__':
    unittest.main()
