"""Owner-token storage and owner-scoped appointment access.

The frontend sends a per-browser UUID in the X-Owner-Token header. A
successful booking stores it as `ownerId` on the new appointment; a missing
or malformed token is ignored. Every user-facing appointment path - GET
/webhook/appointments, GET /webhook/reminders, chat viewing, cancel and
update lookups and their confirmations - only reaches appointments owned by
the request's token. Legacy records without an `ownerId` are reachable by
nobody. Availability is not owner-scoped: every appointment, including
legacy ones, still occupies its slot. The token and `ownerId` are never
returned or logged. This separates browsers; it is not authentication.

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
SESSION = "5e550000-0000-4000-8000-000000000001"
BOOKING = {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"}
UNKNOWN_ID = "99999999-9999-4999-8999-999999999999"
LEGACY = {"name": "Legacy Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "11:00"}


class OwnerTokenTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        tmp = self.tmp_dir.name
        self.appointments_file = os.path.join(tmp, 'appointments.json')
        self.reminders_file = os.path.join(tmp, 'reminders.json')
        patches = [
            patch.object(chatbot_logic, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(chatbot_logic, 'PENDING_FILE', os.path.join(tmp, 'pending_appointments.json')),
            patch.object(chatbot_logic, 'PENDING_UPDATE_FILE', os.path.join(tmp, 'pending_update.json')),
            patch.object(chatbot_logic, 'PENDING_CANCELLATION_FILE', os.path.join(tmp, 'pending_cancellation.json')),
            patch.object(availability_service, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(reminder_service, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(reminder_service, 'REMINDERS_FILE', self.reminders_file),
            patch.dict('os.environ', {'CLINIC_TIMEZONE': 'Europe/London'}, clear=False),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.test_client()
        self.responses = []

    def post(self, intent, parameters=None, owner=None, session=SESSION):
        headers = {"X-Owner-Token": owner} if owner is not None else {}
        body = {"queryResult": {"intent": {"displayName": intent}, "parameters": parameters or {}}}
        if session:
            body["session"] = session
        response = self.client.post('/webhook/webhook', json=body, headers=headers).get_json()
        self.responses.append(response)
        return response

    def get(self, path, owner=None):
        headers = {"X-Owner-Token": owner} if owner is not None else {}
        body = self.client.get(path, headers=headers).get_json()
        self.responses.append(body)
        return body

    def book(self, owner=None, **overrides):
        self.assertEqual(self.post("Book Appointment", {**BOOKING, **overrides}, owner)["context"]["bookingStage"], "confirm")
        booked = self.post("YesIntent", owner=owner)
        self.assertEqual(booked["context"]["bookingStage"], "booked")
        return booked["messages"][0]["content"]["appointment"]

    def saved(self):
        with open(self.appointments_file) as f:
            return json.load(f)

    def add_legacy_record(self):
        records = self.saved() if os.path.exists(self.appointments_file) else []
        records.append(dict(LEGACY))
        with open(self.appointments_file, 'w') as f:
            json.dump(records, f)

    def pending_files(self):
        return sorted(f for f in os.listdir(self.tmp_dir.name) if f.startswith("pending_"))

    @staticmethod
    def text(response):
        return response["messages"][0]["content"]["text"]

    @staticmethod
    def without_meta(response):
        return {key: value for key, value in response.items() if key != "meta"}


class OwnerTokenStorageTest(OwnerTokenTestCase):
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
        self.assertEqual({k: record[k] for k in ("name", "providerId", "date", "time")}, BOOKING)

    def test_a_malformed_token_still_books_without_an_owner_id(self):
        for value in ["", "not-a-uuid", OWNER_A + "x", "{" + OWNER_A + "}", "../../etc/passwd"]:
            with self.subTest(value=value):
                with open(self.appointments_file, 'w') as f:
                    json.dump([], f)
                self.book(owner=value)
                self.assertNotIn("ownerId", self.saved()[0])

    def test_the_owner_is_kept_when_the_appointment_is_updated(self):
        appointment = self.book(owner=OWNER_A)
        self.post("Update Appointment", {"id": appointment["id"], "date": "2026-12-30", "time": "11:00"}, OWNER_A)
        self.assertEqual(self.post("YesIntent", owner=OWNER_A)["context"]["updateStage"], "updated")
        self.assertEqual(self.saved()[0]["ownerId"], OWNER_A)


class AppointmentListingTest(OwnerTokenTestCase):
    def test_the_owner_sees_only_their_active_appointments(self):
        mine = self.book(owner=OWNER_A)
        self.book(owner=OWNER_B, time="10:30")
        cancelled = self.book(owner=OWNER_A, time="11:30")
        self.post("Cancel Appointment", {"id": cancelled["id"]}, OWNER_A)
        self.post("YesIntent", owner=OWNER_A)

        listed = self.get('/webhook/appointments', OWNER_A)

        self.assertEqual(listed, [mine])

    def test_another_owner_and_no_or_malformed_token_see_nothing(self):
        self.book(owner=OWNER_A)
        for owner in (OWNER_B, None, "", "not-a-uuid", OWNER_A + "x"):
            with self.subTest(owner=owner):
                self.assertEqual(self.get('/webhook/appointments', owner), [])

    def test_legacy_records_are_never_listed(self):
        mine = self.book(owner=OWNER_A)
        self.add_legacy_record()
        self.assertEqual(self.get('/webhook/appointments', OWNER_A), [mine])
        self.assertEqual(self.get('/webhook/appointments', None), [])


class ChatViewingTest(OwnerTokenTestCase):
    def test_the_owner_sees_their_appointment(self):
        mine = self.book(owner=OWNER_A)
        self.assertEqual(
            self.text(self.post("View Appointments", owner=OWNER_A)),
            f"Here are the scheduled appointments:\nTest Patient on 2026-12-28 at 10:00 (ID: {mine['id']})",
        )

    def test_another_owner_no_token_and_legacy_records_see_nothing(self):
        self.book(owner=OWNER_A)
        self.add_legacy_record()
        empty = self.without_meta(self.post("View Appointments", owner=OWNER_B, session=None))
        self.assertEqual(self.text(empty), "You don't have any appointments booked at the moment.")
        self.assertEqual(self.without_meta(self.post("View Appointments", session=None)), empty)

    def test_no_data_file_at_all_gets_the_same_reply_as_an_empty_list(self):
        self.assertFalse(os.path.exists(self.appointments_file))
        self.assertEqual(
            self.text(self.post("View Appointments", owner=OWNER_A)),
            "You don't have any appointments booked at the moment.",
        )


class AccessByIdOrNameTest(OwnerTokenTestCase):
    """Another owner's appointment is indistinguishable from one that does
    not exist: the same reply, no pending state, and none of its details.
    """

    def assert_no_details_of(self, appointment, response):
        dumped = json.dumps(response)
        for value in (appointment["id"], "2026-12-28", "10:00", OWNER_A, "Dr. Patel"):
            self.assertNotIn(value, dumped)

    def test_cancel_and_update_by_another_owners_id_look_like_an_unknown_id(self):
        theirs = self.book(owner=OWNER_A)
        for intent in ("Cancel Appointment", "Update Appointment"):
            with self.subTest(intent=intent):
                attempt = self.post(intent, {"id": theirs["id"], "date": "2026-12-30"}, OWNER_B)
                unknown = self.post(intent, {"id": UNKNOWN_ID, "date": "2026-12-30"}, OWNER_B)
                self.assertEqual(self.without_meta(attempt), self.without_meta(unknown))
                self.assert_no_details_of(theirs, attempt)
                self.assertEqual(self.pending_files(), [])

    def test_cancel_and_update_by_another_owners_name_look_like_an_unknown_name(self):
        theirs = self.book(owner=OWNER_A)
        for intent, verb in (("Cancel Appointment", "cancel"), ("Update Appointment", "update")):
            with self.subTest(intent=intent):
                attempt = self.post(intent, {"name": "Test Patient", "date": "2026-12-30"}, OWNER_B)
                self.assertEqual(self.text(attempt), f"I couldn't find an appointment for Test Patient to {verb}.")
                self.assertNotIn("cancellationStage", attempt["context"])
                self.assertNotIn("updateStage", attempt["context"])
                self.assert_no_details_of(theirs, attempt)
                self.assertEqual(self.pending_files(), [])

    def test_without_a_token_nothing_is_found(self):
        theirs = self.book(owner=OWNER_A)
        by_id = self.post("Cancel Appointment", {"id": theirs["id"]}, owner=None)
        unknown = self.post("Cancel Appointment", {"id": UNKNOWN_ID}, owner=None)
        self.assertEqual(self.without_meta(by_id), self.without_meta(unknown))
        by_name = self.post("Cancel Appointment", {"name": "Test Patient"}, owner=None)
        self.assertEqual(self.text(by_name), "I couldn't find an appointment for Test Patient to cancel.")
        self.assertEqual(self.pending_files(), [])

    def test_no_data_file_at_all_gets_the_same_reply_as_not_found(self):
        self.assertFalse(os.path.exists(self.appointments_file))
        self.assertEqual(
            self.text(self.post("Cancel Appointment", {"name": "Test Patient"}, OWNER_A)),
            "I couldn't find an appointment for Test Patient to cancel.",
        )
        self.assertEqual(
            self.text(self.post("Update Appointment", {"name": "Test Patient", "date": "2026-12-30"}, OWNER_A)),
            "I couldn't find an appointment for Test Patient to update.",
        )


class CancellationOwnershipTest(OwnerTokenTestCase):
    def test_the_owner_can_cancel_by_id_and_by_name(self):
        first = self.book(owner=OWNER_A)
        self.book(owner=OWNER_A, time="10:30", name="Other Patient")

        self.assertEqual(self.post("Cancel Appointment", {"id": first["id"]}, OWNER_A)["context"]["cancellationStage"], "confirm")
        self.assertEqual(self.post("YesIntent", owner=OWNER_A)["context"]["cancellationStage"], "cancelled")
        self.assertEqual(self.post("Cancel Appointment", {"name": "Other Patient"}, OWNER_A)["context"]["cancellationStage"], "confirm")
        self.assertEqual(self.post("YesIntent", owner=OWNER_A)["context"]["cancellationStage"], "cancelled")
        self.assertEqual([a.get("status") for a in self.saved()], ["cancelled", "cancelled"])

    def test_confirmation_with_a_changed_token_does_not_cancel(self):
        mine = self.book(owner=OWNER_A)
        for owner in (OWNER_B, None):
            with self.subTest(owner=owner):
                selected = self.post("Cancel Appointment", {"id": mine["id"]}, OWNER_A)
                self.assertEqual(selected["context"]["cancellationStage"], "confirm")
                rejected = self.post("YesIntent", owner=owner)
                self.assertNotIn("cancellationStage", rejected["context"])
                self.assertNotIn("status", self.saved()[0])
                self.assertEqual(self.pending_files(), [])

    def test_a_pending_cancellation_replayed_from_another_conversation_cannot_cancel(self):
        mine = self.book(owner=OWNER_A)
        self.post("Cancel Appointment", {"id": mine["id"]}, OWNER_A)
        # Another owner who somehow knows this conversation's session id.
        rejected = self.post("YesIntent", owner=OWNER_B, session=SESSION)
        self.assertNotIn("cancellationStage", rejected["context"])
        self.assertNotIn("status", self.saved()[0])

    def test_a_legacy_record_cannot_be_cancelled_even_with_a_hand_written_pending_file(self):
        self.add_legacy_record()
        self.assertIn("couldn't find", self.text(self.post("Cancel Appointment", {"name": LEGACY["name"]}, OWNER_A)))
        pending = os.path.join(self.tmp_dir.name, f"pending_cancellations.{SESSION}.json")
        with open(pending, 'w') as f:
            json.dump({"name": LEGACY["name"], "date": LEGACY["date"], "time": LEGACY["time"]}, f)

        rejected = self.post("YesIntent", owner=OWNER_A)

        self.assertNotIn("cancellationStage", rejected["context"])
        self.assertEqual(self.saved(), [LEGACY])
        self.assertFalse(os.path.exists(pending))


class UpdateOwnershipTest(OwnerTokenTestCase):
    def test_the_owner_can_update_by_id_and_by_name(self):
        mine = self.book(owner=OWNER_A)
        self.assertEqual(
            self.post("Update Appointment", {"id": mine["id"], "date": "2026-12-30"}, OWNER_A)["context"]["updateStage"],
            "confirm",
        )
        self.assertEqual(self.post("YesIntent", owner=OWNER_A)["context"]["updateStage"], "updated")
        self.assertEqual(
            self.post("Update Appointment", {"name": "Test Patient", "time": "11:00"}, OWNER_A)["context"]["updateStage"],
            "confirm",
        )
        self.assertEqual(self.post("YesIntent", owner=OWNER_A)["context"]["updateStage"], "updated")
        self.assertEqual((self.saved()[0]["date"], self.saved()[0]["time"]), ("2026-12-30", "11:00"))

    def test_confirmation_with_a_changed_token_does_not_update(self):
        mine = self.book(owner=OWNER_A)
        for owner in (OWNER_B, None):
            with self.subTest(owner=owner):
                self.assertEqual(
                    self.post("Update Appointment", {"id": mine["id"], "date": "2026-12-30"}, OWNER_A)["context"]["updateStage"],
                    "confirm",
                )
                rejected = self.post("YesIntent", owner=owner)
                self.assertNotIn("updateStage", rejected["context"])
                self.assertEqual(self.saved()[0]["date"], "2026-12-28")
                self.assertEqual(self.pending_files(), [])

    def test_a_pending_update_replayed_from_another_conversation_cannot_update(self):
        mine = self.book(owner=OWNER_A)
        self.post("Update Appointment", {"id": mine["id"], "date": "2026-12-30"}, OWNER_A)
        rejected = self.post("YesIntent", owner=OWNER_B, session=SESSION)
        self.assertNotIn("updateStage", rejected["context"])
        self.assertEqual(self.saved()[0]["date"], "2026-12-28")

    def test_a_legacy_record_cannot_be_updated_even_with_a_hand_written_pending_file(self):
        self.add_legacy_record()
        attempt = self.post("Update Appointment", {"name": LEGACY["name"], "date": "2026-12-30"}, OWNER_A)
        self.assertIn("couldn't find", self.text(attempt))
        pending = os.path.join(self.tmp_dir.name, f"pending_updates.{SESSION}.json")
        with open(pending, 'w') as f:
            json.dump({"name": LEGACY["name"], "originalDate": LEGACY["date"], "originalTime": LEGACY["time"],
                       "newDate": "2026-12-30"}, f)

        rejected = self.post("YesIntent", owner=OWNER_A)

        self.assertNotIn("updateStage", rejected["context"])
        self.assertEqual(self.saved(), [LEGACY])
        self.assertFalse(os.path.exists(pending))

    def test_an_update_is_still_checked_against_every_owners_appointments(self):
        # Only the owner's record can be selected, but the new time is checked
        # against everyone's: B's 10:30 and the legacy 11:00 both block.
        mine = self.book(owner=OWNER_A)
        self.book(owner=OWNER_B, time="10:30")
        self.add_legacy_record()
        for taken in ("10:30", "11:00"):
            with self.subTest(taken=taken):
                attempt = self.post("Update Appointment", {"id": mine["id"], "time": taken}, OWNER_A)
                self.assertEqual(attempt["context"]["updateStage"], "fields")
                self.assertEqual(self.pending_files(), [])
        free = self.post("Update Appointment", {"id": mine["id"], "time": "11:30"}, OWNER_A)
        self.assertEqual(free["context"]["updateStage"], "confirm")


class RemindersTest(OwnerTokenTestCase):
    def test_reminders_are_scoped_to_the_owners_appointments(self):
        mine = self.book(owner=OWNER_A)
        theirs = self.book(owner=OWNER_B, time="10:30")
        with open(self.reminders_file) as f:
            stored = json.load(f)
        self.assertEqual({r["appointmentId"] for r in stored}, {mine["id"], theirs["id"]})

        mine_listed = self.get('/webhook/reminders', OWNER_A)
        self.assertEqual([r["appointmentId"] for r in mine_listed], [mine["id"]])
        self.assertEqual(mine_listed, [r for r in stored if r["appointmentId"] == mine["id"]])
        for owner in (None, "not-a-uuid"):
            with self.subTest(owner=owner):
                self.assertEqual(self.get('/webhook/reminders', owner), [])

    def test_reminders_of_a_cancelled_appointment_stay_visible_to_its_owner(self):
        mine = self.book(owner=OWNER_A)
        self.post("Cancel Appointment", {"id": mine["id"]}, OWNER_A)
        self.post("YesIntent", owner=OWNER_A)
        listed = self.get('/webhook/reminders', OWNER_A)
        self.assertEqual([(r["appointmentId"], r["status"]) for r in listed], [(mine["id"], "cancelled")])


class NeverReturnedOrLoggedTest(OwnerTokenTestCase):
    def test_owner_id_and_tokens_never_appear_in_any_response(self):
        with self.assertLogs(level=logging.DEBUG) as logs:
            mine = self.book(owner=OWNER_A)
            self.book(owner=OWNER_B, time="10:30")
            self.post("View Appointments", owner=OWNER_A)
            self.post("Cancel Appointment", {"id": mine["id"]}, OWNER_A)
            self.post("NoIntent", owner=OWNER_A)
            self.post("Update Appointment", {"id": mine["id"], "date": "2026-12-30"}, OWNER_A)
            self.post("YesIntent", owner=OWNER_A)
            self.get('/webhook/appointments', OWNER_A)
            self.get('/webhook/reminders', OWNER_A)

        self.assertNotIn("ownerId", mine)
        dumped = json.dumps(self.responses)
        for secret in ("ownerId", OWNER_A, OWNER_B):
            self.assertNotIn(secret, dumped)
        self.assertTrue(logs.output)
        for secret in (OWNER_A, OWNER_B):
            self.assertNotIn(secret, "\n".join(logs.output))


class AvailabilityStaysGlobalTest(OwnerTokenTestCase):
    def slot_values(self, owner):
        reply = self.post("Book Appointment", {k: v for k, v in BOOKING.items() if k != "time"}, owner, session=None)
        self.assertEqual(reply["context"]["bookingStage"], "slot")
        return [s["value"] for s in reply["messages"][0]["suggestions"]]

    def test_every_owners_appointments_and_legacy_records_block_their_slots(self):
        self.book(owner=OWNER_A)
        self.add_legacy_record()

        for time in ("10:00", "11:00"):
            self.assertFalse(availability_service.is_slot_available("dr-patel", "2026-12-28", time))
        slots_a, slots_b, slots_none = self.slot_values(OWNER_A), self.slot_values(OWNER_B), self.slot_values(None)
        self.assertEqual(slots_a, slots_b)
        self.assertEqual(slots_a, slots_none)
        self.assertNotIn("10:00", slots_a)
        self.assertNotIn("11:00", slots_a)

        for owner in (OWNER_B, None):
            with self.subTest(owner=owner):
                retry = self.post("Book Appointment", BOOKING, owner, session=None)
                self.assertEqual(retry["context"]["bookingStage"], "slot")
        self.assertEqual(len(self.saved()), 2)


if __name__ == '__main__':
    unittest.main()
