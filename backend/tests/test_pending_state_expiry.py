"""Tests that pending booking/update/cancellation state expires 30 minutes
after its file was last written, and that stale pending files from any
conversation are swept - while every non-pending file is left alone.

Ages are simulated with os.utime() on files in a temp directory; the real
backend/*.json files are never read or written.
"""
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from app import app
from backend import availability_service, chatbot_logic, reminder_service

TTL = chatbot_logic._PENDING_TTL_SECONDS
SESSION_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SESSION_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
APPOINTMENT_ID = "11111111-1111-4111-8111-111111111111"
BOOKING = {"name": "Sagar", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"}
NO_PENDING_YES = "There is no appointment pending confirmation."


class PendingStateExpiryTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.tmp = self.tmp_dir.name
        self.appointments_file = self.path('appointments.json')
        patches = [
            patch.object(chatbot_logic, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(chatbot_logic, 'PENDING_FILE', self.path('pending_appointments.json')),
            patch.object(chatbot_logic, 'PENDING_UPDATE_FILE', self.path('pending_update.json')),
            patch.object(chatbot_logic, 'PENDING_CANCELLATION_FILE', self.path('pending_cancellation.json')),
            patch.object(availability_service, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(reminder_service, 'APPOINTMENTS_FILE', self.appointments_file),
            patch.object(reminder_service, 'REMINDERS_FILE', self.path('reminders.json')),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.test_client()

    # --- helpers ---

    def path(self, name):
        return os.path.join(self.tmp, name)

    def post(self, intent, parameters=None, session=SESSION_A):
        body = {"queryResult": {"intent": {"displayName": intent}, "parameters": parameters or {}}}
        if session is not None:
            body["session"] = session
        return self.client.post('/webhook/webhook', json=body).get_json()

    def text(self, response):
        return response["messages"][0]["content"]["text"]

    def age(self, name, seconds):
        stamp = time.time() - seconds
        os.utime(self.path(name), (stamp, stamp))

    def write(self, name, content="[]", age_seconds=0):
        with open(self.path(name), 'w') as f:
            f.write(content)
        self.age(name, age_seconds)

    def saved(self):
        if not os.path.exists(self.appointments_file):
            return []
        with open(self.appointments_file) as f:
            return json.load(f)

    def seed_appointment(self):
        with open(self.appointments_file, 'w') as f:
            json.dump([{"id": APPOINTMENT_ID, "name": "Sagar", "providerId": "dr-patel",
                        "date": "2026-12-28", "time": "10:00"}], f)

    def files(self):
        return sorted(os.listdir(self.tmp))

    # --- fresh pending state behaves exactly as before ---

    def test_fresh_pending_booking_confirms(self):
        self.post("Book Appointment", BOOKING)
        self.age(f"pending_appointments.{SESSION_A}.json", TTL - 60)
        booked = self.post("YesIntent")
        self.assertEqual(booked["context"]["bookingStage"], "booked")
        self.assertEqual([a["name"] for a in self.saved()], ["Sagar"])

    def test_fresh_pending_update_confirms(self):
        self.seed_appointment()
        self.post("Update Appointment", {"id": APPOINTMENT_ID, "date": "2026-12-30", "time": "11:00"})
        self.age(f"pending_updates.{SESSION_A}.json", TTL - 60)
        updated = self.post("YesIntent")
        self.assertEqual(updated["context"]["updateStage"], "updated")
        self.assertEqual(self.saved()[0]["date"], "2026-12-30")

    def test_fresh_pending_cancellation_confirms(self):
        self.seed_appointment()
        self.post("Cancel Appointment", {"id": APPOINTMENT_ID})
        self.age(f"pending_cancellations.{SESSION_A}.json", TTL - 60)
        cancelled = self.post("YesIntent")
        self.assertEqual(cancelled["context"]["cancellationStage"], "cancelled")
        self.assertEqual(self.saved()[0]["status"], "cancelled")

    # --- expired pending state is treated as absent ---

    def test_expired_pending_booking_is_absent(self):
        self.post("Book Appointment", BOOKING)
        self.age(f"pending_appointments.{SESSION_A}.json", TTL + 60)
        response = self.post("YesIntent")
        self.assertEqual(self.text(response), NO_PENDING_YES)
        self.assertNotIn("bookingStage", response["context"])
        self.assertEqual(self.saved(), [])
        self.assertNotIn(f"pending_appointments.{SESSION_A}.json", self.files())

    def test_expired_pending_update_is_absent(self):
        self.seed_appointment()
        self.post("Update Appointment", {"id": APPOINTMENT_ID, "date": "2026-12-30", "time": "11:00"})
        self.age(f"pending_updates.{SESSION_A}.json", TTL + 60)
        response = self.post("YesIntent")
        self.assertEqual(self.text(response), NO_PENDING_YES)
        self.assertNotIn("updateStage", response["context"])
        self.assertEqual((self.saved()[0]["date"], self.saved()[0]["time"]), ("2026-12-28", "10:00"))
        self.assertNotIn(f"pending_updates.{SESSION_A}.json", self.files())

    def test_expired_pending_cancellation_is_absent(self):
        self.seed_appointment()
        self.post("Cancel Appointment", {"id": APPOINTMENT_ID})
        self.age(f"pending_cancellations.{SESSION_A}.json", TTL + 60)
        response = self.post("YesIntent")
        self.assertEqual(self.text(response), NO_PENDING_YES)
        self.assertNotIn("cancellationStage", response["context"])
        self.assertNotIn("status", self.saved()[0])
        self.assertNotIn(f"pending_cancellations.{SESSION_A}.json", self.files())

    def test_expired_state_no_longer_blocks_a_new_action(self):
        self.seed_appointment()
        self.post("Cancel Appointment", {"id": APPOINTMENT_ID})
        refused = self.post("Book Appointment", {"name": "Sagar"})
        self.assertIn("already have another appointment action waiting", self.text(refused))

        self.age(f"pending_cancellations.{SESSION_A}.json", TTL + 60)
        started = self.post("Book Appointment", {"name": "Sagar"})
        self.assertEqual(started["context"]["bookingStage"], "provider")

    def test_legacy_pending_files_expire(self):
        self.post("Book Appointment", BOOKING, session=None)
        self.assertIn("pending_appointments.json", self.files())
        self.age("pending_appointments.json", TTL + 60)
        response = self.post("YesIntent", session=None)
        self.assertEqual(self.text(response), NO_PENDING_YES)
        self.assertEqual(self.saved(), [])

        self.write("pending_update.json", '{"id": "x"}', TTL + 60)
        self.write("pending_cancellation.json", '{"id": "x"}', TTL + 60)
        self.post("View Appointments", session=SESSION_A)
        self.assertEqual([n for n in self.files() if n.startswith("pending_")], [])

    # --- sweep of other conversations' files ---

    def test_stale_files_of_other_sessions_are_swept(self):
        for prefix in chatbot_logic._SESSION_PENDING_PREFIXES:
            self.write(f"{prefix}.{SESSION_C}.json", "{}", TTL + 60)
        self.post("View Appointments")
        self.assertEqual([n for n in self.files() if n.startswith("pending_")], [])

    def test_fresh_files_of_other_sessions_are_preserved(self):
        names = [f"{prefix}.{SESSION_C}.json" for prefix in chatbot_logic._SESSION_PENDING_PREFIXES]
        for name in names:
            self.write(name, "{}", TTL - 60)
        self.post("View Appointments")
        self.assertEqual([n for n in self.files() if n.startswith("pending_")], sorted(names))

    def test_sweep_never_deletes_non_pending_or_look_alike_files(self):
        protected = [
            "appointments.json", "reminders.json", "providers.json", "provider_availability.json",
            "notes.txt",
            "pending_appointments.not-a-uuid.json",
            f"pending_appointments.{SESSION_C.upper()}.json",
            f"pending_appointments.{SESSION_C.replace('-', '')}.json",
            f"pending_appointments.{{{SESSION_C}}}.json",
            f"pending_appointments.{SESSION_C}.json.tmp",
            f".pending_appointments.{SESSION_C}.json.0123abcd.tmp",
            f"pending_appointments.{SESSION_C}.json.bak",
            f"pending_other.{SESSION_C}.json",
            f"pending_appointments.{SESSION_C}.extra.json",
            "pending_appointments..json",
            f"xpending_appointments.{SESSION_C}.json",
        ]
        for name in protected:
            self.write(name, "[]", TTL * 100)
        self.post("View Appointments")
        for name in protected:
            self.assertIn(name, self.files(), name)

    # --- boundary, races and errors ---

    def test_boundary_just_under_ttl_is_kept_and_just_over_expires(self):
        self.write(f"pending_appointments.{SESSION_C}.json", "{}", TTL - 5)
        self.write(f"pending_updates.{SESSION_C}.json", "{}", TTL + 5)
        self.post("View Appointments")
        self.assertIn(f"pending_appointments.{SESSION_C}.json", self.files())
        self.assertNotIn(f"pending_updates.{SESSION_C}.json", self.files())

    def test_file_refreshed_after_listing_is_not_deleted(self):
        name = f"pending_appointments.{SESSION_C}.json"
        self.write(name, "{}", TTL + 60)
        real_listdir = os.listdir

        def listdir_then_refresh(directory):
            names = real_listdir(directory)
            if directory == self.tmp:
                self.age(name, 0)  # another request rewrites it right after the listing
            return names

        with patch.object(chatbot_logic.os, 'listdir', side_effect=listdir_then_refresh):
            self.post("View Appointments")
        self.assertIn(name, self.files())

    def test_file_that_disappears_before_deletion_is_ignored(self):
        name = f"pending_appointments.{SESSION_C}.json"
        self.write(name, "{}", TTL + 60)
        real_rename = os.rename

        def rename_raced(src, dst):
            if src == self.path(name):
                os.remove(src)  # another request deleted it first
            return real_rename(src, dst)

        with patch.object(chatbot_logic.os, 'rename', side_effect=rename_raced):
            with patch.object(chatbot_logic.logger, 'warning') as warning:
                response = self.post("View Appointments")
        self.assertTrue(response["success"])
        warning.assert_not_called()
        self.assertEqual(self.files(), [])

    def test_refresh_between_age_check_and_deletion_is_kept(self):
        # The TOCTOU race: the file is stale when its age is checked, then -
        # before the cleaner acts - another request rewrites it
        # (write_json_atomic -> a new, fresh file). The refresh is injected
        # immediately after the first age check, so this applies to any
        # check-then-act implementation. The refreshed file must survive.
        name = f"pending_appointments.{SESSION_C}.json"
        self.write(name, '{"name": "Old"}', TTL + 60)
        real_getmtime = os.path.getmtime
        refreshed = []

        def getmtime_then_refresh(path):
            mtime = real_getmtime(path)
            if path == self.path(name) and not refreshed:
                refreshed.append(True)
                chatbot_logic.atomic_json.write_json_atomic(path, {"name": "Refreshed"})
            return mtime  # the cleaner saw the old, stale age

        with patch.object(chatbot_logic.os.path, 'getmtime', side_effect=getmtime_then_refresh):
            with patch.object(chatbot_logic.logger, 'warning') as warning:
                response = self.post("View Appointments")
        self.assertTrue(response["success"])
        self.assertEqual(refreshed, [True])
        warning.assert_not_called()
        with open(self.path(name)) as f:
            self.assertEqual(json.load(f), {"name": "Refreshed"})
        self.assertEqual(self.files(), [name])  # no claimed/hidden leftovers

    def test_even_newer_write_during_restore_is_not_overwritten(self):
        name = f"pending_appointments.{SESSION_C}.json"
        self.write(name, '{"name": "Old"}', TTL + 60)
        real_rename, real_link = os.rename, os.link

        def refresh_then_rename(src, dst):
            if src == self.path(name):
                chatbot_logic.atomic_json.write_json_atomic(src, {"name": "Refreshed"})
            return real_rename(src, dst)

        def newest_then_link(src, dst):
            chatbot_logic.atomic_json.write_json_atomic(dst, {"name": "Newest"})
            return real_link(src, dst)

        with patch.object(chatbot_logic.os, 'rename', side_effect=refresh_then_rename), \
                patch.object(chatbot_logic.os, 'link', side_effect=newest_then_link):
            response = self.post("View Appointments")
        self.assertTrue(response["success"])
        with open(self.path(name)) as f:
            self.assertEqual(json.load(f), {"name": "Newest"})
        self.assertEqual(self.files(), [name])

    def test_deletion_error_is_tolerated_and_logged_safely(self):
        self.write(f"pending_appointments.{SESSION_C}.json", '{"name": "Secret Patient"}', TTL + 60)
        with patch.object(chatbot_logic.os, 'remove', side_effect=PermissionError("denied: Secret Patient")):
            with self.assertLogs('backend.chatbot_logic', level='WARNING') as logs:
                response = self.post("View Appointments")
        self.assertTrue(response["success"])
        self.assertEqual(
            logs.output,
            ["WARNING:backend.chatbot_logic:pending state cleanup failed "
             "kind=pending_appointments exception_type=PermissionError"],
        )
        joined = "\n".join(logs.output)
        self.assertNotIn(SESSION_C, joined)
        self.assertNotIn("Secret Patient", joined)

    def test_unreadable_directory_does_not_fail_the_request(self):
        with patch.object(chatbot_logic.os, 'listdir', side_effect=PermissionError("denied")):
            with self.assertLogs('backend.chatbot_logic', level='WARNING') as logs:
                response = self.post("View Appointments")
        self.assertTrue(response["success"])
        self.assertEqual(logs.output, ["WARNING:backend.chatbot_logic:pending state sweep failed exception_type=PermissionError"])

    # --- pending file format is unchanged ---

    def test_pending_json_schema_is_unchanged(self):
        self.post("Book Appointment", BOOKING)
        with open(self.path(f"pending_appointments.{SESSION_A}.json")) as f:
            self.assertEqual(json.load(f), BOOKING)
        self.seed_appointment()
        self.post("NoIntent")
        self.post("Cancel Appointment", {"id": APPOINTMENT_ID})
        with open(self.path(f"pending_cancellations.{SESSION_A}.json")) as f:
            self.assertEqual(json.load(f), {"id": APPOINTMENT_ID})


if __name__ == '__main__':
    unittest.main()
