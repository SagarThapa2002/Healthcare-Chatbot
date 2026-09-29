"""Tests for backend/atomic_json.py's write_json_atomic() and its use by the
backend's JSON persistence paths.

Every data file here lives in a temp directory - the real backend/*.json
files are never read or written.
"""
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app import app
from backend import atomic_json, availability_service, chatbot_logic, reminder_service
from backend.atomic_json import write_json_atomic


def legacy_write(path, data):
    """The write this helper replaced, byte for byte."""
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


class Unserializable:
    pass


class WriteJsonAtomicTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.dir = self.tmp_dir.name
        self.path = os.path.join(self.dir, 'data.json')

    def read_bytes(self, path):
        with open(path, 'rb') as f:
            return f.read()

    def test_normal_write_produces_the_expected_json(self):
        data = [{"name": "Test Patient", "date": "2026-12-28", "time": "10:00"}]
        write_json_atomic(self.path, data)
        with open(self.path) as f:
            self.assertEqual(json.load(f), data)
        self.assertEqual(os.listdir(self.dir), ['data.json'])

    def test_output_is_byte_identical_to_the_previous_json_dump_write(self):
        data = [
            {"name": "Zoë Ångström", "providerId": "dr-patel", "nested": {"a": [1, 2.5, None, True]}},
            {},
        ]
        legacy_path = os.path.join(self.dir, 'legacy.json')
        legacy_write(legacy_path, data)
        write_json_atomic(self.path, data)
        self.assertEqual(self.read_bytes(self.path), self.read_bytes(legacy_path))
        self.assertEqual(self.read_bytes(self.path), json.dumps(data, indent=2).encode('ascii'))

    def test_existing_file_is_replaced_with_the_new_complete_contents(self):
        legacy_write(self.path, [{"old": True}] * 50)
        write_json_atomic(self.path, [{"new": True}])
        self.assertEqual(self.read_bytes(self.path), json.dumps([{"new": True}], indent=2).encode())
        self.assertEqual(os.listdir(self.dir), ['data.json'])

    def test_serialization_failure_leaves_the_existing_file_untouched(self):
        legacy_write(self.path, [{"old": True}])
        before = self.read_bytes(self.path)
        # json.dump streams output, so without atomic replacement the
        # first element would already be written before this fails.
        with self.assertRaises(TypeError):
            write_json_atomic(self.path, [{"new": True}, Unserializable()])
        self.assertEqual(self.read_bytes(self.path), before)
        self.assertEqual(os.listdir(self.dir), ['data.json'])

    def test_serialization_failure_on_a_new_file_creates_nothing(self):
        with self.assertRaises(TypeError):
            write_json_atomic(self.path, [Unserializable()])
        self.assertEqual(os.listdir(self.dir), [])

    def test_fsync_failure_leaves_the_existing_file_and_no_temp_file(self):
        legacy_write(self.path, [{"old": True}])
        before = self.read_bytes(self.path)
        with patch('backend.atomic_json.os.fsync', side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                write_json_atomic(self.path, [{"new": True}])
        self.assertEqual(self.read_bytes(self.path), before)
        self.assertEqual(os.listdir(self.dir), ['data.json'])

    def test_replace_failure_leaves_the_existing_file_and_no_temp_file(self):
        legacy_write(self.path, [{"old": True}])
        before = self.read_bytes(self.path)
        with patch('backend.atomic_json.os.replace', side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                write_json_atomic(self.path, [{"new": True}])
        self.assertEqual(self.read_bytes(self.path), before)
        self.assertEqual(os.listdir(self.dir), ['data.json'])

    def test_temp_file_is_created_in_the_destination_directory_and_fsynced(self):
        real_replace = os.replace
        with patch('backend.atomic_json.os.replace', side_effect=real_replace) as spy_replace, \
                patch('backend.atomic_json.os.fsync', wraps=os.fsync) as spy_fsync:
            write_json_atomic(self.path, [1])
        src, dst = spy_replace.call_args.args
        self.assertEqual(os.path.dirname(os.path.abspath(src)), os.path.abspath(self.dir))
        self.assertEqual(dst, self.path)
        self.assertNotEqual(os.path.basename(src), 'data.json')
        spy_fsync.assert_called_once()

    def test_existing_file_permissions_are_preserved(self):
        legacy_write(self.path, [])
        os.chmod(self.path, 0o640)
        write_json_atomic(self.path, [1])
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o640)

    def test_new_file_gets_the_same_permissions_as_a_plain_open(self):
        legacy_path = os.path.join(self.dir, 'legacy.json')
        legacy_write(legacy_path, [])
        write_json_atomic(self.path, [])
        self.assertEqual(
            stat.S_IMODE(os.stat(self.path).st_mode), stat.S_IMODE(os.stat(legacy_path).st_mode)
        )


class PersistencePathsUseAtomicWritesTest(unittest.TestCase):
    """Drives the real booking -> update -> cancel webhook flow (and the
    reminder CLI's processing path) against temp data files, recording
    every write that goes through write_json_atomic.
    """

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
            patch.dict('os.environ', {'CLINIC_TIMEZONE': 'Europe/London'}, clear=False),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        self.written = []
        real_write = atomic_json.write_json_atomic

        def recording_write(path, data):
            real_write(path, data)
            self.written.append(path)
            self.assert_valid_formatted_json(path, data)

        patcher = patch.object(atomic_json, 'write_json_atomic', side_effect=recording_write)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = app.test_client()

    def assert_valid_formatted_json(self, path, data):
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), json.dumps(data, indent=2).encode('ascii'))

    def post(self, intent, parameters=None):
        body = {"queryResult": {"intent": {"displayName": intent}, "parameters": parameters or {}}}
        return self.client.post('/webhook/webhook', json=body).get_json()

    def read(self, key):
        with open(self.files[key]) as f:
            return json.load(f)

    def test_booking_update_and_cancel_flows_write_through_the_helper(self):
        confirm = self.post("Book Appointment", {
            "name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00",
        })
        self.assertEqual(confirm["context"]["bookingStage"], "confirm")
        self.assertEqual(self.written, [self.files['pending']])

        booked = self.post("YesIntent")
        self.assertEqual(booked["context"]["bookingStage"], "booked")
        appointment_id = booked["messages"][0]["content"]["appointment"]["id"]
        self.assertEqual(self.read('appointments')[0]["id"], appointment_id)
        self.assertEqual(len(self.read('reminders')), 1)

        update = self.post("Update Appointment", {"id": appointment_id, "date": "2026-12-30", "time": "11:00"})
        self.assertEqual(update["context"]["updateStage"], "confirm")
        updated = self.post("YesIntent")
        self.assertEqual(updated["context"]["updateStage"], "updated")
        self.assertEqual(self.read('appointments')[0]["date"], "2026-12-30")

        cancel = self.post("Cancel Appointment", {"id": appointment_id})
        self.assertEqual(cancel["context"]["cancellationStage"], "confirm")
        cancelled = self.post("YesIntent")
        self.assertEqual(cancelled["context"]["cancellationStage"], "cancelled")
        self.assertEqual(self.read('appointments')[0]["status"], "cancelled")

        self.assertEqual(
            set(self.written),
            {self.files[key] for key in
             ('appointments', 'pending', 'pending_update', 'pending_cancellation', 'reminders')},
        )
        for key in ('pending', 'pending_update', 'pending_cancellation'):
            self.assertFalse(os.path.exists(self.files[key]))
        self.assertEqual(
            sorted(os.listdir(self.tmp_dir.name)), ['appointments.json', 'reminders.json']
        )

    def test_reminder_cli_processing_writes_through_the_helper(self):
        self.post("Book Appointment", {
            "name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00",
        })
        self.post("YesIntent")
        self.written.clear()

        processed = reminder_service.process_due_reminders(
            lambda reminder, appointment: True,
            now=datetime(2026, 12, 28, tzinfo=timezone.utc),
            path=self.files['reminders'],
            appointments_path=self.files['appointments'],
        )
        self.assertEqual([r["status"] for r in processed], ["sent"])
        self.assertEqual(self.written, [self.files['reminders']])
        self.assertEqual(self.read('reminders')[0]["status"], "sent")

    def test_failed_appointment_write_leaves_existing_data_intact(self):
        self.post("Book Appointment", {
            "name": "First", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00",
        })
        self.post("YesIntent")
        with open(self.files['appointments'], 'rb') as f:
            before = f.read()

        self.post("Book Appointment", {
            "name": "Second", "providerId": "dr-patel", "date": "2026-12-28", "time": "11:00",
        })
        with patch('backend.atomic_json.os.replace', side_effect=OSError("disk full")):
            failed = self.post("YesIntent")

        # Existing failure behaviour is unchanged: the webhook's generic
        # error envelope, and the pending booking stays for a retry.
        self.assertFalse(failed["success"])
        self.assertEqual(failed["error"]["code"], "INTERNAL_ERROR")
        self.assertTrue(os.path.exists(self.files['pending']))
        with open(self.files['appointments'], 'rb') as f:
            self.assertEqual(f.read(), before)
        self.assertNotIn('.tmp', ' '.join(os.listdir(self.tmp_dir.name)))


if __name__ == '__main__':
    unittest.main()
