"""Tests that pending booking/update/cancellation state is isolated per
conversation "session" (a client-generated UUID in the webhook payload),
and that requests without a valid session keep using the legacy global
pending files exactly as before.

Drives the real webhook. Every data file is redirected to a temp directory;
the real backend/*.json files are never read or written.
"""
import json
import logging
import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import availability_service, chatbot_logic, reminder_service

SESSION_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SESSION_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
APPOINTMENT_ID = "11111111-1111-4111-8111-111111111111"

BOOK_A = {"name": "Sagar", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"}
BOOK_B = {"name": "Alex", "providerId": "dr-patel", "date": "2026-12-28", "time": "11:00"}

LEGACY_FILES = {"pending_appointments.json", "pending_update.json", "pending_cancellation.json"}

# What a conversation with nothing pending gets back for a bare yes/no - the
# booking handlers' replies, never another flow's.
NO_PENDING_REPLIES = {
    "YesIntent": "There is no appointment pending confirmation.",
    "NoIntent": "There is no pending appointment to cancel.",
}


class ConversationIsolationTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp = self.tmp_dir.name
        self.appointments_file = os.path.join(self.tmp, 'appointments.json')
        patches = [
            patch.object(chatbot_logic, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(chatbot_logic, 'PENDING_FILE', os.path.join(self.tmp, 'pending_appointments.json')),
            patch.object(chatbot_logic, 'PENDING_UPDATE_FILE', os.path.join(self.tmp, 'pending_update.json')),
            patch.object(chatbot_logic, 'PENDING_CANCELLATION_FILE', os.path.join(self.tmp, 'pending_cancellation.json')),
            patch.object(availability_service, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(reminder_service, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(reminder_service, 'REMINDERS_FILE', os.path.join(self.tmp, 'reminders.json')),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.test_client()

    # --- helpers ---

    def post(self, intent, parameters=None, session=None, include_session=True):
        body = {"queryResult": {"intent": {"displayName": intent}, "parameters": parameters or {}}}
        if include_session and session is not None:
            body["session"] = session
        return self.client.post('/webhook/webhook', json=body).get_json()

    def text(self, response):
        return response["messages"][0]["content"]["text"]

    def path(self, name):
        return os.path.join(self.tmp, name)

    def read(self, name):
        with open(self.path(name)) as f:
            return json.load(f)

    def pending_files(self):
        return sorted(n for n in os.listdir(self.tmp) if n.startswith("pending_"))

    def saved(self):
        if not os.path.exists(self.appointments_file):
            return []
        with open(self.appointments_file) as f:
            return json.load(f)

    def seed_appointment(self):
        with open(self.appointments_file, 'w') as f:
            json.dump([{"id": APPOINTMENT_ID, "name": "Sagar", "providerId": "dr-patel",
                        "date": "2026-12-28", "time": "10:00"}], f)

    # --- bookings ---

    def test_b_reaching_confirmation_does_not_overwrite_a(self):
        self.assertEqual(self.post("Book Appointment", BOOK_A, SESSION_A)["context"]["bookingStage"], "confirm")
        self.assertEqual(self.post("Book Appointment", BOOK_B, SESSION_B)["context"]["bookingStage"], "confirm")
        self.assertEqual(self.read(f"pending_appointments.{SESSION_A}.json")["name"], "Sagar")
        self.assertEqual(self.read(f"pending_appointments.{SESSION_B}.json")["name"], "Alex")

    def test_a_reaching_confirmation_does_not_overwrite_b(self):
        self.post("Book Appointment", BOOK_B, SESSION_B)
        self.post("Book Appointment", BOOK_A, SESSION_A)
        self.assertEqual(self.read(f"pending_appointments.{SESSION_B}.json")["name"], "Alex")
        self.assertEqual(self.read(f"pending_appointments.{SESSION_A}.json")["name"], "Sagar")

    def test_each_yes_confirms_only_its_own_booking(self):
        self.post("Book Appointment", BOOK_A, SESSION_A)
        self.post("Book Appointment", BOOK_B, SESSION_B)

        booked_a = self.post("YesIntent", session=SESSION_A)
        self.assertEqual(booked_a["context"]["bookingStage"], "booked")
        self.assertEqual(booked_a["messages"][0]["content"]["appointment"]["name"], "Sagar")
        self.assertEqual([(a["name"], a["time"]) for a in self.saved()], [("Sagar", "10:00")])
        # Completing A left B's pending booking intact.
        self.assertFalse(os.path.exists(self.path(f"pending_appointments.{SESSION_A}.json")))
        self.assertEqual(self.read(f"pending_appointments.{SESSION_B}.json")["name"], "Alex")

        booked_b = self.post("YesIntent", session=SESSION_B)
        self.assertEqual(booked_b["messages"][0]["content"]["appointment"]["name"], "Alex")
        self.assertEqual([(a["name"], a["time"]) for a in self.saved()], [("Sagar", "10:00"), ("Alex", "11:00")])
        self.assertEqual(self.pending_files(), [])

    def test_no_clears_only_its_own_pending_booking(self):
        self.post("Book Appointment", BOOK_A, SESSION_A)
        self.post("Book Appointment", BOOK_B, SESSION_B)

        declined = self.post("NoIntent", session=SESSION_A)
        self.assertIn("Appointment booking has been canceled", self.text(declined))
        self.assertEqual(self.pending_files(), [f"pending_appointments.{SESSION_B}.json"])

        booked_b = self.post("YesIntent", session=SESSION_B)
        self.assertEqual(booked_b["context"]["bookingStage"], "booked")
        self.assertEqual([a["name"] for a in self.saved()], ["Alex"])

    def test_a_stray_yes_from_another_conversation_finds_nothing(self):
        self.post("Book Appointment", BOOK_A, SESSION_A)
        stray = self.post("YesIntent", session=SESSION_B)
        self.assertEqual(self.text(stray), "There is no appointment pending confirmation.")
        self.assertEqual(self.saved(), [])
        self.assertTrue(os.path.exists(self.path(f"pending_appointments.{SESSION_A}.json")))

    # --- cancellation and update ---

    def test_pending_cancellation_cannot_be_confirmed_or_declined_by_another_conversation(self):
        self.seed_appointment()
        confirm = self.post("Cancel Appointment", {"id": APPOINTMENT_ID}, SESSION_A)
        self.assertEqual(confirm["context"]["cancellationStage"], "confirm")

        stray_yes = self.post("YesIntent", session=SESSION_B)
        self.assertEqual(self.text(stray_yes), NO_PENDING_REPLIES["YesIntent"])
        self.assertNotIn("cancellationStage", stray_yes["context"])
        stray_no = self.post("NoIntent", session=SESSION_B)
        self.assertEqual(self.text(stray_no), NO_PENDING_REPLIES["NoIntent"])
        self.assertNotIn("cancellationStage", stray_no["context"])
        self.assertNotIn("status", self.saved()[0])
        self.assertEqual(self.read(f"pending_cancellations.{SESSION_A}.json"), {"id": APPOINTMENT_ID})

        cancelled = self.post("YesIntent", session=SESSION_A)
        self.assertEqual(cancelled["context"]["cancellationStage"], "cancelled")
        self.assertEqual(self.saved()[0]["status"], "cancelled")
        self.assertEqual(self.pending_files(), [])

    def test_pending_update_cannot_be_confirmed_or_declined_by_another_conversation(self):
        self.seed_appointment()
        confirm = self.post("Update Appointment", {"id": APPOINTMENT_ID, "date": "2026-12-30", "time": "11:00"}, SESSION_A)
        self.assertEqual(confirm["context"]["updateStage"], "confirm")

        stray_yes = self.post("YesIntent", session=SESSION_B)
        self.assertEqual(self.text(stray_yes), NO_PENDING_REPLIES["YesIntent"])
        self.assertNotIn("updateStage", stray_yes["context"])
        stray_no = self.post("NoIntent", session=SESSION_B)
        self.assertEqual(self.text(stray_no), NO_PENDING_REPLIES["NoIntent"])
        self.assertNotIn("updateStage", stray_no["context"])
        self.assertEqual((self.saved()[0]["date"], self.saved()[0]["time"]), ("2026-12-28", "10:00"))
        self.assertEqual(self.read(f"pending_updates.{SESSION_A}.json")["id"], APPOINTMENT_ID)

        updated = self.post("YesIntent", session=SESSION_A)
        self.assertEqual(updated["context"]["updateStage"], "updated")
        self.assertEqual((self.saved()[0]["date"], self.saved()[0]["time"]), ("2026-12-30", "11:00"))
        self.assertEqual(self.pending_files(), [])

    # --- mutual exclusion ---

    def test_mutual_exclusion_still_applies_within_one_conversation(self):
        self.seed_appointment()
        self.post("Cancel Appointment", {"id": APPOINTMENT_ID}, SESSION_A)
        refused = self.post("Book Appointment", {"name": "Sagar"}, SESSION_A)
        self.assertIsNone(refused["context"].get("bookingStage"))
        self.assertIn("already have another appointment action waiting", self.text(refused))

    def test_a_pending_action_does_not_block_another_conversation(self):
        self.seed_appointment()
        self.post("Cancel Appointment", {"id": APPOINTMENT_ID}, SESSION_A)
        started = self.post("Book Appointment", BOOK_B, SESSION_B)
        self.assertEqual(started["context"]["bookingStage"], "confirm")
        self.assertEqual(self.pending_files(), sorted([
            f"pending_appointments.{SESSION_B}.json", f"pending_cancellations.{SESSION_A}.json",
        ]))

    # --- legacy / no-session behaviour ---

    def test_missing_session_uses_the_legacy_global_files(self):
        self.post("Book Appointment", BOOK_A, include_session=False)
        self.assertEqual(self.pending_files(), ["pending_appointments.json"])
        booked = self.post("YesIntent", include_session=False)
        self.assertEqual(booked["context"]["bookingStage"], "booked")
        self.assertEqual(self.pending_files(), [])

    def test_legacy_and_session_state_do_not_see_each_other(self):
        self.post("Book Appointment", BOOK_A, include_session=False)
        self.assertEqual(self.text(self.post("YesIntent", session=SESSION_B)),
                         "There is no appointment pending confirmation.")
        self.post("Book Appointment", BOOK_B, SESSION_B)
        self.assertEqual(self.post("YesIntent", include_session=False)["messages"][0]["content"]["appointment"]["name"],
                         "Sagar")
        self.assertTrue(os.path.exists(self.path(f"pending_appointments.{SESSION_B}.json")))

    def test_legacy_pending_cancellation_and_update_are_invisible_to_sessions(self):
        # Guards the YesIntent/NoIntent routing and the mutual-exclusion
        # check: no session request may see a legacy (no-session) pending file.
        self.seed_appointment()
        self.post("Cancel Appointment", {"id": APPOINTMENT_ID}, include_session=False)
        self.assertEqual(self.pending_files(), ["pending_cancellation.json"])
        for intent, reply in NO_PENDING_REPLIES.items():
            response = self.post(intent, session=SESSION_B)
            self.assertEqual(self.text(response), reply)
            self.assertNotIn("cancellationStage", response["context"])
        self.assertEqual(self.post("Book Appointment", BOOK_B, SESSION_B)["context"]["bookingStage"], "confirm")
        self.post("NoIntent", session=SESSION_B)
        self.assertNotIn("status", self.saved()[0])
        self.assertEqual(self.pending_files(), ["pending_cancellation.json"])
        # Only a legacy (no-session) "no" clears the legacy cancellation.
        self.assertIn("left that appointment unchanged", self.text(self.post("NoIntent", include_session=False)))
        self.assertEqual(self.pending_files(), [])

        self.post("Update Appointment", {"id": APPOINTMENT_ID, "date": "2026-12-30", "time": "11:00"},
                  include_session=False)
        self.assertEqual(self.pending_files(), ["pending_update.json"])
        for intent, reply in NO_PENDING_REPLIES.items():
            response = self.post(intent, session=SESSION_B)
            self.assertEqual(self.text(response), reply)
            self.assertNotIn("updateStage", response["context"])
        self.assertEqual((self.saved()[0]["date"], self.saved()[0]["time"]), ("2026-12-28", "10:00"))
        self.assertEqual(self.pending_files(), ["pending_update.json"])

    def test_malformed_sessions_fall_back_to_the_legacy_files(self):
        malformed = [
            "", "not-a-uuid", 12345, None, ["a"], {"id": SESSION_A},
            SESSION_A.replace("-", ""),        # bare hex
            "{" + SESSION_A + "}",             # braces
            "urn:uuid:" + SESSION_A,           # urn form
            SESSION_A + "0",                   # overlong
            " " + SESSION_A[1:],               # whitespace, right length
        ]
        for value in malformed:
            with self.subTest(session=value):
                response = self.post("Book Appointment", BOOK_A, session=value)
                self.assertEqual(response["context"]["bookingStage"], "confirm")
                self.assertEqual(self.pending_files(), ["pending_appointments.json"])
                self.post("NoIntent", session=value)
                self.assertEqual(self.pending_files(), [])

    def test_uppercase_uuid_is_the_same_conversation(self):
        self.post("Book Appointment", BOOK_A, session=SESSION_A.upper())
        self.assertEqual(self.pending_files(), [f"pending_appointments.{SESSION_A}.json"])
        self.assertEqual(self.post("YesIntent", session=SESSION_A)["context"]["bookingStage"], "booked")

    def test_path_traversal_like_sessions_cannot_escape_the_data_directory(self):
        parent = os.path.dirname(self.tmp)
        before = set(os.listdir(parent))
        for value in ["../../../../tmp/evil", "../pending_appointments", "/etc/passwd",
                      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa/.", "..\\..\\windows-aaaaaaaa-aaaa-aaaa-aaaa"]:
            with self.subTest(session=value):
                self.post("Book Appointment", BOOK_A, session=value)
                self.assertEqual(self.pending_files(), ["pending_appointments.json"])
                self.post("NoIntent", session=value)
        self.assertEqual(set(os.listdir(parent)), before)
        self.assertEqual(sorted(os.listdir(self.tmp)), [])

    def test_valid_sessions_get_their_own_files_for_every_pending_kind(self):
        self.seed_appointment()
        self.post("Book Appointment", BOOK_B, SESSION_A)
        self.post("Cancel Appointment", {"id": APPOINTMENT_ID}, SESSION_B)
        third = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        self.post("Update Appointment", {"id": APPOINTMENT_ID, "date": "2026-12-30", "time": "11:00"}, third)
        self.assertEqual(self.pending_files(), sorted([
            f"pending_appointments.{SESSION_A}.json",
            f"pending_cancellations.{SESSION_B}.json",
            f"pending_updates.{third}.json",
        ]))
        self.assertFalse(LEGACY_FILES & set(os.listdir(self.tmp)))

    # --- no session data leaks into records or logs ---

    def test_session_id_is_not_stored_in_appointments_or_logged(self):
        with self.assertLogs(level=logging.DEBUG) as logs:
            self.post("Book Appointment", BOOK_A, SESSION_A)
            self.post("YesIntent", session=SESSION_A)
        saved = self.saved()
        self.assertEqual(len(saved), 1)
        self.assertNotIn("session", saved[0])
        self.assertNotIn(SESSION_A, json.dumps(saved))
        self.assertFalse([line for line in logs.output if SESSION_A in line])


if __name__ == '__main__':
    unittest.main()
