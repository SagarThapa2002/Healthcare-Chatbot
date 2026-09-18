import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import chatbot_logic


class WebhookTestCase(unittest.TestCase):
    """Every test redirects chatbot_logic's appointment file paths to a
    temporary directory before touching the webhook, so the real
    backend/appointments.json (which holds a genuine booking) is never
    read from or written to by any test in this class.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

        self.appointments_file = os.path.join(self.tmp_dir.name, 'appointments.json')
        self.pending_file = os.path.join(self.tmp_dir.name, 'pending_appointments.json')

        patcher_appointments = patch.object(chatbot_logic, 'APPOINTMENTS_FILE', self.appointments_file)
        patcher_pending = patch.object(chatbot_logic, 'PENDING_FILE', self.pending_file)
        patcher_appointments.start()
        patcher_pending.start()
        self.addCleanup(patcher_appointments.stop)
        self.addCleanup(patcher_pending.stop)

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
        # Step through booking exactly as the real frontend drives it - the
        # backend itself does no validation of these fields.
        self.post_webhook("Book Appointment", {"name": "Test Patient"})
        self.post_webhook("Book Appointment", {"name": "Test Patient", "date": "2026-12-26"})
        confirm = self.post_webhook(
            "Book Appointment", {"name": "Test Patient", "date": "2026-12-26", "time": "10:00"}
        ).get_json()
        self.assertEqual(confirm["messages"][0]["type"], "text")
        self.assertIn("yes or no", confirm["messages"][0]["content"]["text"])

        booked = self.post_webhook("YesIntent").get_json()
        message = booked["messages"][0]

        self.assertTrue(booked["success"])
        self.assertEqual(message["type"], "booking_confirmation")
        self.assertEqual(
            message["content"]["appointment"],
            {"name": "Test Patient", "date": "2026-12-26", "time": "10:00"},
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


if __name__ == '__main__':
    unittest.main()
