"""Owner-token plumbing (not yet an ownership boundary).

The frontend sends a per-browser UUID in the X-Owner-Token header. A
successful booking stores it as `ownerId` on the new appointment; a missing
or malformed token is ignored. The token is never returned or logged, and
nothing is filtered by it yet: viewing, cancelling, updating and
availability behave exactly as without it.

All data files are redirected to a temp directory; the real backend/*.json
files are never read or written.
"""
import json
import logging
import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import availability_service, chatbot_logic, reminder_service

OWNER_A = "0a0a0a0a-0a0a-4a0a-8a0a-0a0a0a0a0a0a"
OWNER_B = "0b0b0b0b-0b0b-4b0b-8b0b-0b0b0b0b0b0b"
BOOKING = {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"}


class OwnerTokenTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        tmp = self.tmp_dir.name
        self.appointments_file = os.path.join(tmp, 'appointments.json')
        patches = [
            patch.object(chatbot_logic, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(chatbot_logic, 'PENDING_FILE', os.path.join(tmp, 'pending_appointments.json')),
            patch.object(chatbot_logic, 'PENDING_UPDATE_FILE', os.path.join(tmp, 'pending_update.json')),
            patch.object(chatbot_logic, 'PENDING_CANCELLATION_FILE', os.path.join(tmp, 'pending_cancellation.json')),
            patch.object(availability_service, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(reminder_service, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(reminder_service, 'REMINDERS_FILE', os.path.join(tmp, 'reminders.json')),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.test_client()

    def post(self, intent, parameters=None, owner=None):
        headers = {"X-Owner-Token": owner} if owner is not None else {}
        body = {"queryResult": {"intent": {"displayName": intent}, "parameters": parameters or {}}}
        return self.client.post('/webhook/webhook', json=body, headers=headers).get_json()

    def book(self, owner=None, **overrides):
        self.assertEqual(self.post("Book Appointment", {**BOOKING, **overrides}, owner)["context"]["bookingStage"], "confirm")
        booked = self.post("YesIntent", owner=owner)
        self.assertEqual(booked["context"]["bookingStage"], "booked")
        return booked

    def saved(self):
        with open(self.appointments_file) as f:
            return json.load(f)

    @staticmethod
    def without_meta(response):
        return {key: value for key, value in response.items() if key != "meta"}

    # --- storage ---

    def test_a_valid_owner_token_is_stored_as_owner_id(self):
        self.book(owner=OWNER_A)
        self.assertEqual(self.saved()[0]["ownerId"], OWNER_A)

    def test_an_uppercase_token_is_stored_in_canonical_lowercase_like_the_session(self):
        self.book(owner=OWNER_A.upper())
        self.assertEqual(self.saved()[0]["ownerId"], OWNER_A)

    def test_a_missing_token_still_books_without_an_owner_id(self):
        self.book()
        record = self.saved()[0]
        self.assertNotIn("ownerId", record)
        self.assertEqual(
            {k: record[k] for k in ("name", "providerId", "date", "time")},
            BOOKING,
        )

    def test_a_malformed_token_still_books_without_an_owner_id(self):
        for value in ["", "not-a-uuid", OWNER_A + "x", "{" + OWNER_A + "}", "../../etc/passwd"]:
            with self.subTest(value=value):
                with open(self.appointments_file, 'w') as f:
                    json.dump([], f)
                self.book(owner=value)
                self.assertNotIn("ownerId", self.saved()[0])

    def test_the_owner_is_kept_when_the_appointment_is_updated(self):
        self.book(owner=OWNER_A)
        appointment_id = self.saved()[0]["id"]
        self.post("Update Appointment", {"id": appointment_id, "date": "2026-12-30", "time": "11:00"}, OWNER_A)
        self.assertEqual(self.post("YesIntent", owner=OWNER_A)["context"]["updateStage"], "updated")
        self.assertEqual(self.saved()[0]["ownerId"], OWNER_A)

    # --- never returned or logged ---

    def test_owner_id_is_not_returned_by_get_appointments(self):
        self.book(owner=OWNER_A)
        listed = self.client.get('/webhook/appointments', headers={"X-Owner-Token": OWNER_A}).get_json()
        self.assertEqual(len(listed), 1)
        self.assertNotIn("ownerId", listed[0])
        self.assertEqual(listed[0]["id"], self.saved()[0]["id"])
        self.assertNotIn(OWNER_A, json.dumps(listed))

    def test_owner_id_is_not_returned_in_the_booking_confirmation(self):
        booked = self.book(owner=OWNER_A)
        appointment = booked["messages"][0]["content"]["appointment"]
        self.assertNotIn("ownerId", appointment)
        self.assertEqual(appointment["id"], self.saved()[0]["id"])
        self.assertNotIn(OWNER_A, json.dumps(booked))

    def test_the_token_is_never_logged(self):
        with self.assertLogs(level=logging.DEBUG) as logs:
            self.book(owner=OWNER_A)
            self.client.get('/webhook/appointments', headers={"X-Owner-Token": OWNER_A})
        self.assertTrue(logs.output)
        self.assertNotIn(OWNER_A, "\n".join(logs.output))

    # --- nothing is enforced yet ---

    def test_viewing_is_unchanged_by_any_token(self):
        self.book(owner=OWNER_A)
        responses = [self.without_meta(self.post("View Appointments", owner=owner))
                     for owner in (None, OWNER_A, OWNER_B)]
        self.assertEqual(responses[0], responses[1])
        self.assertEqual(responses[0], responses[2])
        self.assertIn(self.saved()[0]["id"], responses[0]["messages"][0]["content"]["text"])
        listings = [self.client.get('/webhook/appointments', headers=h).get_json()
                    for h in ({}, {"X-Owner-Token": OWNER_B})]
        self.assertEqual(listings[0], listings[1])

    def test_cancellation_is_unchanged_by_another_owners_token(self):
        self.book(owner=OWNER_A)
        appointment_id = self.saved()[0]["id"]
        confirm = self.post("Cancel Appointment", {"id": appointment_id}, OWNER_B)
        self.assertEqual(confirm["context"]["cancellationStage"], "confirm")
        cancelled = self.post("YesIntent", owner=OWNER_B)
        self.assertEqual(cancelled["context"]["cancellationStage"], "cancelled")
        self.assertEqual(self.saved()[0]["status"], "cancelled")

    def test_update_is_unchanged_by_another_owners_token(self):
        self.book(owner=OWNER_A)
        appointment_id = self.saved()[0]["id"]
        confirm = self.post("Update Appointment", {"id": appointment_id, "date": "2026-12-30", "time": "11:00"}, OWNER_B)
        self.assertEqual(confirm["context"]["updateStage"], "confirm")
        self.assertEqual(self.post("YesIntent", owner=OWNER_B)["context"]["updateStage"], "updated")
        self.assertEqual((self.saved()[0]["date"], self.saved()[0]["time"]), ("2026-12-30", "11:00"))

    # --- availability stays global ---

    def test_availability_counts_appointments_regardless_of_owner(self):
        self.book(owner=OWNER_A)
        self.assertFalse(availability_service.is_slot_available("dr-patel", "2026-12-28", "10:00"))
        self.assertNotIn("10:00", availability_service.get_available_slots("dr-patel", "2026-12-28"))

        for owner in (OWNER_B, None):
            with self.subTest(owner=owner):
                retry = self.post("Book Appointment", BOOKING, owner)
                self.assertEqual(retry["context"]["bookingStage"], "slot")
                self.assertNotIn("10:00", [s["value"] for s in retry["messages"][0]["suggestions"]])
        self.assertEqual(len(self.saved()), 1)


if __name__ == '__main__':
    unittest.main()
