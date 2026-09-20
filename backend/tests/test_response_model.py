import unittest
from datetime import datetime

from backend import response_model


class ResponseModelTest(unittest.TestCase):
    def test_text_message_shape(self):
        msg = response_model.text_message("Hello")
        self.assertEqual(msg, {"type": "text", "content": {"text": "Hello"}, "suggestions": []})

    def test_validation_error_message_shape(self):
        # Not currently emitted by any webhook branch (see chatbot_logic.py
        # / response_model.py docstrings) - tested directly here so the
        # type itself is real and correct.
        msg = response_model.validation_error_message("That doesn't look like a date.")
        self.assertEqual(
            msg,
            {
                "type": "validation_error",
                "content": {"text": "That doesn't look like a date."},
                "suggestions": [],
            },
        )

    def test_booking_confirmation_message_shape(self):
        appointment = {"name": "Test Patient", "date": "2026-12-26", "time": "10:00"}
        msg = response_model.booking_confirmation_message("Booked!", appointment)
        self.assertEqual(
            msg,
            {
                "type": "booking_confirmation",
                "content": {"text": "Booked!", "appointment": appointment},
                "suggestions": [],
            },
        )

    def test_symptom_guidance_message_shape(self):
        # Not currently emitted by any webhook branch (see chatbot_logic.py,
        # symptom_triage.py, and SYMPTOM_RULES_SOURCES.md) - tested directly
        # here so the type itself is real and correct ahead of being wired in.
        msg = response_model.symptom_guidance_message(
            "TEST MESSAGE - synthetic fixture", "emergency", ["test-emergency-fever-phrase"]
        )
        self.assertEqual(
            msg,
            {
                "type": "symptom_guidance",
                "content": {
                    "text": "TEST MESSAGE - synthetic fixture",
                    "urgency": "emergency",
                    "matchedRules": ["test-emergency-fever-phrase"],
                },
                "suggestions": [],
            },
        )

    def test_symptom_guidance_message_defaults_to_empty_suggestions(self):
        msg = response_model.symptom_guidance_message("text", "unknown", [])
        self.assertEqual(msg["suggestions"], [])

    def test_assistant_response_message_shape(self):
        msg = response_model.assistant_response_message("Here is some general information.")
        self.assertEqual(
            msg,
            {
                "type": "assistant_response",
                "content": {
                    "text": "Here is some general information.",
                    "provider": "claude",
                    "disclaimer": "AI-generated general information, not medical advice.",
                },
                "suggestions": [],
            },
        )

    def test_assistant_response_message_provider_is_configurable(self):
        msg = response_model.assistant_response_message("text", provider="test-provider")
        self.assertEqual(msg["content"]["provider"], "test-provider")

    def test_success_response_envelope_shape(self):
        messages = [response_model.text_message("Hi")]
        envelope = response_model.success_response(messages, intent="General FAQ")

        self.assertTrue(envelope["success"])
        self.assertIsNone(envelope["error"])
        self.assertEqual(envelope["messages"], messages)
        self.assertEqual(envelope["context"], {"intent": "General FAQ"})
        self.assertEqual(envelope["meta"]["schemaVersion"], "1.0")
        self.assertTrue(envelope["meta"]["requestId"])
        self.assertTrue(envelope["meta"]["timestamp"])

    def test_success_response_request_id_is_unique_per_call(self):
        envelope_a = response_model.success_response([], intent="General FAQ")
        envelope_b = response_model.success_response([], intent="General FAQ")
        self.assertNotEqual(envelope_a["meta"]["requestId"], envelope_b["meta"]["requestId"])

    def test_timestamp_is_valid_iso8601(self):
        envelope = response_model.success_response([], intent="General FAQ")
        # Raises ValueError if this isn't a parseable ISO-8601 timestamp.
        datetime.fromisoformat(envelope["meta"]["timestamp"])

    def test_error_response_envelope_shape(self):
        envelope = response_model.error_response("Oops, something went wrong on the server.")

        self.assertFalse(envelope["success"])
        self.assertEqual(envelope["error"]["code"], "INTERNAL_ERROR")
        self.assertEqual(envelope["error"]["message"], "Oops, something went wrong on the server.")
        self.assertEqual(envelope["messages"], [])
        self.assertIsNone(envelope["context"])


if __name__ == '__main__':
    unittest.main()
