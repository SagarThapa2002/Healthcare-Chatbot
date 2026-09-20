import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import availability_service, chatbot_logic


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
    every booking test in this class.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

        self.appointments_file = os.path.join(self.tmp_dir.name, 'appointments.json')
        self.pending_file = os.path.join(self.tmp_dir.name, 'pending_appointments.json')

        patcher_appointments = patch.object(chatbot_logic, 'APPOINTMENTS_FILE', self.appointments_file)
        patcher_pending = patch.object(chatbot_logic, 'PENDING_FILE', self.pending_file)
        patcher_availability_appointments = patch.object(
            availability_service, 'APPOINTMENTS_FILE', self.appointments_file
        )
        patcher_appointments.start()
        patcher_pending.start()
        patcher_availability_appointments.start()
        self.addCleanup(patcher_appointments.stop)
        self.addCleanup(patcher_pending.stop)
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
        self.assertEqual(
            message["content"]["appointment"],
            {"name": "Test Patient", "providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"},
        )
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

        # Both chatbot_logic's and availability_service's independent
        # APPOINTMENTS_FILE constants must be patched - see
        # WebhookTestCase's setUp docstring above for why.
        patcher_appointments = patch.object(chatbot_logic, 'APPOINTMENTS_FILE', self.appointments_file)
        patcher_pending = patch.object(chatbot_logic, 'PENDING_FILE', self.pending_file)
        patcher_availability_appointments = patch.object(
            availability_service, 'APPOINTMENTS_FILE', self.appointments_file
        )
        patcher_appointments.start()
        patcher_pending.start()
        patcher_availability_appointments.start()
        self.addCleanup(patcher_appointments.stop)
        self.addCleanup(patcher_pending.stop)
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
        self.assertEqual(data["context"], {"intent": "Update Appointment"})
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
        self.assertEqual(data["context"], {"intent": "Cancel Appointment"})
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
        self._book_and_confirm()

        data = self.post_webhook(
            "Update Appointment", {"name": "Test Patient", "date": "2027-01-02"}
        ).get_json()

        self.assertTrue(data["success"])
        self.assertIn("has been updated", data["messages"][0]["content"]["text"])

    def test_cancel_appointment_with_valid_name_still_cancels(self):
        self._book_and_confirm()

        data = self.post_webhook("Cancel Appointment", {"name": "Test Patient"}).get_json()

        self.assertTrue(data["success"])
        self.assertIn("has been successfully canceled", data["messages"][0]["content"]["text"])

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


if __name__ == '__main__':
    unittest.main()
