import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import availability_service, chatbot_logic, reminder_service


class WebhookTestCase(unittest.TestCase):
    """Every test redirects chatbot_logic's appointment file paths to a
    temporary directory before touching the webhook, so the real
    backend/appointments.json (which holds a genuine booking) is never
    read from or written to by any test in this class.

    chatbot_logic.py and availability_service.py each independently
    compute their own APPOINTMENTS_FILE constant (both point at the same
    real file by default) - since Phase 6.1 Slice 3 (Step 2),
    _handle_book_appointment calls into availability_service for
    date/slot availability checks, so both must be patched or that
    "never read from the real file" guarantee above would be broken for
    every booking test in this class. PENDING_CANCELLATION_FILE/
    PENDING_UPDATE_FILE must also be patched - handle_webhook_request
    checks their existence on every YesIntent/NoIntent to decide whether
    to route to the cancellation/update confirm handlers, so leaving
    either unpatched would have that check silently hit the real repo
    path instead of this isolated one.
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

    def test_general_faq_returns_structured_text_message(self):
        data = self.post_webhook("General FAQ").get_json()

        self.assertTrue(data["success"])
        self.assertIsNone(data["error"])
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["type"], "text")
        self.assertIn("virtual healthcare assistant", data["messages"][0]["content"]["text"])
        self.assertEqual(data["messages"][0]["suggestions"], [])
        self.assertEqual(data["context"], {"intent": "General FAQ"})

    def test_meta_has_schema_version_request_id_and_timestamp(self):
        data = self.post_webhook("General FAQ").get_json()

        self.assertEqual(data["meta"]["schemaVersion"], "1.0")
        self.assertTrue(data["meta"]["requestId"])
        self.assertTrue(data["meta"]["timestamp"])

    def test_request_id_differs_between_requests(self):
        first = self.post_webhook("General FAQ").get_json()
        second = self.post_webhook("General FAQ").get_json()
        self.assertNotEqual(first["meta"]["requestId"], second["meta"]["requestId"])

    def test_context_intent_matches_requested_intent(self):
        data = self.post_webhook("Symptom Check", {"symptom": "a headache"}).get_json()
        self.assertEqual(data["context"]["intent"], "Symptom Check")

    def test_symptom_check_without_symptom_prompts_for_one(self):
        data = self.post_webhook("Symptom Check", {}).get_json()
        self.assertEqual(
            data["messages"][0]["content"]["text"],
            "Could you please tell me your symptom so I can assist you better?",
        )

    def test_booking_flow_produces_booking_confirmation_with_appointment(self):
        # Step through booking exactly as the real frontend drives it.
        # Since Phase 6.1 Slice 3 (Step 2), the sequence is
        # name -> provider -> date -> slot -> confirm; "dr-patel" and
        # "2026-12-28" (a real, synthetic provider/Monday - see
        # backend/providers.json / backend/provider_availability.json)
        # are used because the backend now validates the provider and
        # checks real availability for the date/slot, rather than
        # accepting any format-valid strings unconditionally.
        self.post_webhook("Book Appointment", {"name": "Test Patient"})
        self.post_webhook("Book Appointment", {"name": "Test Patient", "providerId": "dr-patel"})
        self.post_webhook(
            "Book Appointment", {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28"}
        )
        confirm = self.post_webhook(
            "Book Appointment",
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        ).get_json()
        self.assertEqual(confirm["messages"][0]["type"], "text")
        self.assertIn("yes or no", confirm["messages"][0]["content"]["text"])

        booked = self.post_webhook("YesIntent").get_json()
        message = booked["messages"][0]

        self.assertTrue(booked["success"])
        self.assertEqual(message["type"], "booking_confirmation")
        appointment = message["content"]["appointment"]
        self.assertEqual(appointment["name"], "Test Patient")
        self.assertEqual(appointment["providerId"], "dr-patel")
        self.assertEqual(appointment["date"], "2026-12-28")
        self.assertEqual(appointment["time"], "10:00")
        # A stable id is generated server-side at booking time (next Phase
        # 6.1 slice) - checked for presence/non-emptiness only, never an
        # exact value, matching this project's existing convention for
        # generated ids (see meta.requestId's own tests).
        self.assertTrue(appointment["id"])
        self.assertIn("has been booked", message["content"]["text"])

        # The booking was written to the temp file, never the real one.
        self.assertTrue(os.path.exists(self.appointments_file))

    def test_yes_intent_without_pending_booking_stays_a_text_message(self):
        data = self.post_webhook("YesIntent").get_json()
        self.assertEqual(data["messages"][0]["type"], "text")
        self.assertEqual(data["messages"][0]["content"]["text"], "There is no appointment pending confirmation.")

    def test_genuine_failure_returns_success_false_without_leaking_internals(self):
        response = self.client.post(
            '/webhook/webhook', data="not valid json", content_type='application/json'
        )
        data = response.get_json()

        self.assertFalse(data["success"])
        self.assertEqual(data["messages"], [])
        self.assertIsNone(data["context"])
        self.assertEqual(data["error"]["message"], "Oops, something went wrong on the server.")
        self.assertNotIn("Traceback", data["error"]["message"])
        self.assertNotIn(os.path.dirname(__file__), data["error"]["message"])
        # A genuine failure still carries a valid, well-formed meta block.
        self.assertEqual(data["meta"]["schemaVersion"], "1.0")


class UpdateCancelAppointmentMissingNameTest(unittest.TestCase):
    """Regression tests for a real, verified bug: the frontend's single-shot
    routing for Update/Cancel Appointment sends {} as parameters (pinned in
    frontend/src/hooks/useConversation.test.js), which used to make
    chatbot_logic._handle_update_appointment / _handle_cancel_appointment
    crash with AttributeError('NoneType' object has no attribute 'lower')
    as soon as name.lower() ran against a None name - whenever the
    appointments file was non-empty. Every test here seeds a real
    appointment first (via the same Book Appointment -> YesIntent flow used
    elsewhere in this file) specifically to exercise that non-empty case.

    Deliberately does NOT subclass WebhookTestCase above: that class already
    has its own real tests, and subclassing a TestCase that carries test_*
    methods makes unittest's discovery inherit and silently re-run them a
    second time under this class's name too. Duplicating the small
    setUp/post_webhook helper here keeps this class's discovered test count
    equal to the number of test_ methods actually defined below - matching
    the existing LLMRoutingTestCase base-with-no-tests-of-its-own pattern in
    test_chatbot_logic_llm_routing.py.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

        self.appointments_file = os.path.join(self.tmp_dir.name, 'appointments.json')
        self.pending_file = os.path.join(self.tmp_dir.name, 'pending_appointments.json')
        self.pending_cancellation_file = os.path.join(self.tmp_dir.name, 'pending_cancellation.json')
        self.pending_update_file = os.path.join(self.tmp_dir.name, 'pending_update.json')

        # Both chatbot_logic's and availability_service's independent
        # APPOINTMENTS_FILE constants must be patched - see
        # WebhookTestCase's setUp docstring above for why. Same for
        # PENDING_CANCELLATION_FILE/PENDING_UPDATE_FILE (also explained
        # there).
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
        self.addCleanup(patcher_pending_update.stop)
        self.addCleanup(patcher_pending_cancellation.stop)
        self.addCleanup(patcher_availability_appointments.stop)

        self.client = app.test_client()

    def post_webhook(self, intent, parameters=None):
        body = {"queryResult": {"intent": {"displayName": intent}, "parameters": parameters or {}}}
        return self.client.post('/webhook/webhook', json=body)

    def _book_and_confirm(self, name="Test Patient", provider_id="dr-patel", date="2026-12-28", time="10:00"):
        # "dr-patel"/"2026-12-28" (a Monday) are a real, synthetic
        # provider/date pair (see backend/providers.json /
        # backend/provider_availability.json) - since Phase 6.1 Slice 3
        # (Step 2), _handle_book_appointment validates the provider and
        # checks real availability, so an arbitrary providerId/date can
        # no longer reach the confirmation step.
        self.post_webhook(
            "Book Appointment",
            {"name": name, "providerId": provider_id, "date": date, "time": time},
        )
        self.post_webhook("YesIntent")

    def test_update_appointment_without_name_does_not_crash(self):
        self._book_and_confirm()

        with patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            response = self.post_webhook("Update Appointment", {})
        data = response.get_json()

        mock_answer.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["success"])
        self.assertIsNone(data["error"])
        self.assertEqual(data["messages"][0]["type"], "text")
        self.assertIn("name", data["messages"][0]["content"]["text"].lower())
        # Phase 6.1 Slice B: update is now a multi-turn, ID-preferring
        # flow - asking for an identifier reports updateStage "identifier"
        # (see response_model.success_response).
        self.assertEqual(data["context"], {"intent": "Update Appointment", "updateStage": "identifier"})
        self.assertEqual(data["meta"]["schemaVersion"], "1.0")

    def test_cancel_appointment_without_name_does_not_crash(self):
        self._book_and_confirm()

        with patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            response = self.post_webhook("Cancel Appointment", {})
        data = response.get_json()

        mock_answer.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data["success"])
        self.assertIsNone(data["error"])
        self.assertEqual(data["messages"][0]["type"], "text")
        self.assertIn("name", data["messages"][0]["content"]["text"].lower())
        # Next Phase 6.1 slice: cancellation is now a multi-turn,
        # ID-preferring flow - asking for an identifier reports
        # cancellationStage "identifier" (see response_model.success_response).
        self.assertEqual(data["context"], {"intent": "Cancel Appointment", "cancellationStage": "identifier"})
        self.assertEqual(data["meta"]["schemaVersion"], "1.0")

    def test_update_appointment_without_parameters_key_does_not_crash(self):
        # queryResult.parameters can be omitted entirely, not just empty -
        # the handler must guard against a None parameters dict too.
        self._book_and_confirm()

        body = {"queryResult": {"intent": {"displayName": "Update Appointment"}}}
        data = self.client.post('/webhook/webhook', json=body).get_json()

        self.assertTrue(data["success"])
        self.assertIn("name", data["messages"][0]["content"]["text"].lower())

    def test_cancel_appointment_without_parameters_key_does_not_crash(self):
        self._book_and_confirm()

        body = {"queryResult": {"intent": {"displayName": "Cancel Appointment"}}}
        data = self.client.post('/webhook/webhook', json=body).get_json()

        self.assertTrue(data["success"])
        self.assertIn("name", data["messages"][0]["content"]["text"].lower())

    def test_update_appointment_with_valid_name_still_updates(self):
        # Phase 6.1 Slice B: update now requires explicit confirmation -
        # a unique name still resolves unambiguously, and the proposed new
        # date is validated, but nothing is written until an explicit
        # "yes". "2027-01-04" is a Monday - dr-patel's real, synthetic
        # availability (see BookingFlowTestCase's own docstring for this
        # data) - so the unchanged 10:00 time from _book_and_confirm still
        # lands on a valid, open slot for that provider.
        self._book_and_confirm()

        identify = self.post_webhook(
            "Update Appointment", {"name": "Test Patient", "date": "2027-01-04"}
        ).get_json()
        self.assertIn("yes or no", identify["messages"][0]["content"]["text"])

        data = self.post_webhook("YesIntent").get_json()

        self.assertTrue(data["success"])
        self.assertIn("has been updated", data["messages"][0]["content"]["text"])

    def test_cancel_appointment_with_valid_name_still_cancels(self):
        # Next Phase 6.1 slice: cancellation now requires explicit
        # confirmation - a unique name still resolves unambiguously, but
        # an explicit "yes" is required before anything changes.
        self._book_and_confirm()

        identify = self.post_webhook("Cancel Appointment", {"name": "Test Patient"}).get_json()
        self.assertIn("yes or no", identify["messages"][0]["content"]["text"])

        data = self.post_webhook("YesIntent").get_json()

        self.assertTrue(data["success"])
        self.assertIn("has been cancelled", data["messages"][0]["content"]["text"])

    def test_update_appointment_with_unmatched_name_reports_not_found_not_a_crash(self):
        self._book_and_confirm()

        data = self.post_webhook(
            "Update Appointment", {"name": "Nobody Booked This Name", "date": "2027-01-02"}
        ).get_json()

        self.assertTrue(data["success"])
        self.assertIn("couldn't find an appointment", data["messages"][0]["content"]["text"])

    def test_cancel_appointment_with_unmatched_name_reports_not_found_not_a_crash(self):
        self._book_and_confirm()

        data = self.post_webhook(
            "Cancel Appointment", {"name": "Nobody Booked This Name"}
        ).get_json()

        self.assertTrue(data["success"])
        self.assertIn("couldn't find an appointment", data["messages"][0]["content"]["text"])


class GetRemindersTest(unittest.TestCase):
    """Isolated tests for GET /webhook/reminders - self-contained, not a
    subclass of WebhookTestCase above (that class isolates only
    chatbot_logic's/availability_service's own APPOINTMENTS_FILE-family
    constants, never reminder_service.REMINDERS_FILE). Every test here
    redirects reminder_service.REMINDERS_FILE to a temp path first, so
    the real backend/reminders.json is never read from or written to by
    any test in this class - and backend/appointments.json is never even
    referenced by this read-only, appointment-data-free endpoint.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.reminders_file = os.path.join(self.tmp_dir.name, 'reminders.json')

        patcher = patch.object(reminder_service, 'REMINDERS_FILE', self.reminders_file)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.client = app.test_client()

    def _write_reminders(self, reminders):
        with open(self.reminders_file, 'w') as f:
            json.dump(reminders, f)

    def test_empty_reminders_file_returns_empty_list(self):
        self._write_reminders([])

        response = self.client.get('/webhook/reminders')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_missing_reminders_file_returns_empty_list(self):
        # self.reminders_file is deliberately never created in this test -
        # reminder_service.list_reminders() must tolerate a missing file.
        response = self.client.get('/webhook/reminders')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])

    def test_populated_reminder_is_returned_with_exact_fields(self):
        reminder = {
            "id": "r1",
            "appointmentId": "a1",
            "type": "24h_before",
            "sendAt": "2026-12-01T00:00:00+00:00",
            "status": "pending",
            "createdAt": "2026-11-01T00:00:00+00:00",
            "sentAt": None,
            "failureReason": None,
        }
        self._write_reminders([reminder])

        response = self.client.get('/webhook/reminders')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [reminder])

    def test_multiple_mixed_status_reminders_are_all_returned(self):
        reminders = [
            {
                "id": "r-pending", "appointmentId": "a1", "type": "24h_before",
                "sendAt": "2026-12-01T00:00:00+00:00", "status": "pending",
                "createdAt": "2026-11-01T00:00:00+00:00", "sentAt": None, "failureReason": None,
            },
            {
                "id": "r-sent", "appointmentId": "a2", "type": "24h_before",
                "sendAt": "2026-01-01T00:00:00+00:00", "status": "sent",
                "createdAt": "2025-12-01T00:00:00+00:00", "sentAt": "2026-01-01T00:00:00+00:00",
                "failureReason": None,
            },
            {
                "id": "r-failed", "appointmentId": "a3", "type": "24h_before",
                "sendAt": "2026-02-01T00:00:00+00:00", "status": "failed",
                "createdAt": "2026-01-01T00:00:00+00:00", "sentAt": None,
                "failureReason": "send_failed",
            },
            {
                "id": "r-cancelled", "appointmentId": "a4", "type": "24h_before",
                "sendAt": "2026-03-01T00:00:00+00:00", "status": "cancelled",
                "createdAt": "2026-02-01T00:00:00+00:00", "sentAt": None, "failureReason": None,
            },
        ]
        self._write_reminders(reminders)

        response = self.client.get('/webhook/reminders')

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(len(body), 4)
        statuses = {r["id"]: r["status"] for r in body}
        self.assertEqual(
            statuses,
            {"r-pending": "pending", "r-sent": "sent", "r-failed": "failed", "r-cancelled": "cancelled"},
        )

    def test_response_never_contains_appointment_domain_fields(self):
        reminder = {
            "id": "r1", "appointmentId": "a1", "type": "24h_before",
            "sendAt": "2026-12-01T00:00:00+00:00", "status": "pending",
            "createdAt": "2026-11-01T00:00:00+00:00", "sentAt": None, "failureReason": None,
        }
        self._write_reminders([reminder])

        response = self.client.get('/webhook/reminders')

        body = response.get_json()
        for forbidden_field in ("name", "date", "time", "providerId", "durationMinutes"):
            self.assertNotIn(forbidden_field, body[0])

    def test_real_repository_data_files_are_not_touched(self):
        real_reminders_path = os.path.join(os.path.dirname(reminder_service.__file__), 'reminders.json')
        real_appointments_path = os.path.join(
            os.path.dirname(reminder_service.__file__), 'appointments.json'
        )
        with open(real_reminders_path) as f:
            before_reminders = f.read()
        with open(real_appointments_path) as f:
            before_appointments = f.read()

        self._write_reminders([{
            "id": "r1", "appointmentId": "a1", "type": "24h_before",
            "sendAt": "2026-12-01T00:00:00+00:00", "status": "pending",
            "createdAt": "2026-11-01T00:00:00+00:00", "sentAt": None, "failureReason": None,
        }])
        self.client.get('/webhook/reminders')

        with open(real_reminders_path) as f:
            after_reminders = f.read()
        with open(real_appointments_path) as f:
            after_appointments = f.read()
        self.assertEqual(before_reminders, after_reminders)
        self.assertEqual(before_appointments, after_appointments)


if __name__ == '__main__':
    unittest.main()
