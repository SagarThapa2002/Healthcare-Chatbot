"""Tests for Phase 5.5's privacy-aware, metadata-only logging.

Every test captures real logger output via unittest.TestCase.assertLogs and
asserts directly on it - proving what is/isn't actually emitted, not just
that a code path was reached. Appointment file I/O is isolated to a temp
directory exactly like test_webhook.py, so the real backend/appointments.json
is never read from or written to here.
"""
import os
import re
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import assistant_service, chatbot_logic, claude_provider, llm_config


def _request_id_from(log_lines):
    """Extracts the first request_id=<value> token found in a list of
    captured log lines (as produced by assertLogs()'s `.output`)."""
    for line in log_lines:
        match = re.search(r"request_id=(\S+)", line)
        if match:
            return match.group(1)
    return None


class WebhookLoggingTestCase(unittest.TestCase):
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


class SensitiveContentNeverLoggedTest(WebhookLoggingTestCase):
    def test_patient_name_and_appointment_details_never_appear_in_logs(self):
        with self.assertLogs('backend', level='INFO') as cm:
            self.post_webhook(
                "Book Appointment",
                {"name": "Very Specific Patient Name", "date": "2026-12-26", "time": "10:00"},
            )
        combined = "\n".join(cm.output)
        self.assertNotIn("Very Specific Patient Name", combined)
        self.assertNotIn("2026-12-26", combined)
        self.assertNotIn("10:00", combined)

    def test_symptom_text_never_appears_in_logs(self):
        with self.assertLogs('backend', level='INFO') as cm:
            self.post_webhook("Symptom Check", {"symptom": "a very specific rare symptom description"})
        combined = "\n".join(cm.output)
        self.assertNotIn("a very specific rare symptom description", combined)

    def test_general_faq_message_text_never_appears_in_logs(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            mock_answer.return_value = {
                "allowed": True,
                "category": "allowed",
                "text": "Some response text nobody should log the question for.",
                "source": "llm",
                "provider": "claude",
            }
            with self.assertLogs('backend', level='INFO') as cm:
                self.post_webhook("General FAQ", {"message": "a very specific private health question"})
        combined = "\n".join(cm.output)
        self.assertNotIn("a very specific private health question", combined)
        self.assertNotIn("Some response text nobody should log the question for.", combined)


class RequestIdCorrelationTest(WebhookLoggingTestCase):
    def test_logged_request_id_matches_response_request_id(self):
        with self.assertLogs('backend.webhook', level='INFO') as cm:
            data = self.post_webhook("General FAQ", {}).get_json()

        logged_id = _request_id_from(cm.output)
        self.assertIsNotNone(logged_id)
        self.assertEqual(logged_id, data["meta"]["requestId"])

    def test_chatbot_logic_logs_the_same_request_id_as_webhook(self):
        with self.assertLogs('backend', level='INFO') as cm:
            data = self.post_webhook("Symptom Check", {"symptom": "a headache"}).get_json()

        webhook_lines = [line for line in cm.output if "backend.webhook" in line]
        chatbot_lines = [line for line in cm.output if "backend.chatbot_logic" in line]
        self.assertTrue(webhook_lines)
        self.assertTrue(chatbot_lines)

        webhook_id = _request_id_from(webhook_lines)
        chatbot_id = _request_id_from(chatbot_lines)
        self.assertEqual(webhook_id, chatbot_id)
        self.assertEqual(webhook_id, data["meta"]["requestId"])


class FailureLoggingTest(WebhookLoggingTestCase):
    def test_failure_log_has_exception_type_but_not_raw_body_text(self):
        with self.assertLogs('backend.webhook', level='ERROR') as cm:
            response = self.client.post(
                '/webhook/webhook', data="not valid json", content_type='application/json'
            )
        combined = "\n".join(cm.output)
        self.assertIn("exception_type=", combined)
        self.assertNotIn("not valid json", combined)
        self.assertNotIn("Traceback", combined)

        data = response.get_json()
        logged_id = _request_id_from(cm.output)
        self.assertIsNotNone(logged_id)
        self.assertEqual(logged_id, data["meta"]["requestId"])


class SuccessfulRequestLogsMetadataOnlyTest(WebhookLoggingTestCase):
    def test_successful_general_faq_logs_intent_and_success_only(self):
        with self.assertLogs('backend.webhook', level='INFO') as cm:
            self.post_webhook("General FAQ", {})

        completed = [line for line in cm.output if "webhook request completed" in line]
        self.assertEqual(len(completed), 1)
        self.assertIn("intent=General FAQ", completed[0])
        self.assertIn("success=True", completed[0])


class AssistantServiceLoggingTest(unittest.TestCase):
    """Exercises backend/assistant_service.py's logging directly - the fact
    that chatbot_logic.py threads the same request_id into it is already
    covered by RequestIdCorrelationTest above.
    """

    def test_allowed_llm_response_logs_category_and_provider_without_message_or_answer_text(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            mock_generate.return_value = "This exact answer text must never be logged."

            with self.assertLogs('backend.assistant_service', level='INFO') as cm:
                assistant_service.answer(
                    "This exact question text must never be logged either.",
                    request_id="test-request-id",
                )

        combined = "\n".join(cm.output)
        self.assertIn("test-request-id", combined)
        self.assertIn("category=allowed", combined)
        self.assertIn("provider=claude", combined)
        self.assertNotIn("This exact answer text must never be logged.", combined)
        self.assertNotIn("This exact question text must never be logged either.", combined)

    def test_refused_category_is_logged_without_the_message_text(self):
        with self.assertLogs('backend.assistant_service', level='INFO') as cm:
            assistant_service.answer(
                "Do I have a specific rare disease?", request_id="test-request-id-2"
            )

        combined = "\n".join(cm.output)
        self.assertIn("test-request-id-2", combined)
        self.assertIn("category=diagnosis_request", combined)
        self.assertNotIn("Do I have a specific rare disease?", combined)

    def test_provider_failure_logs_exception_type_not_message_text(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            mock_generate.side_effect = claude_provider.ProviderAPIError(
                "sensitive internal detail that must not leak"
            )

            with self.assertLogs('backend.assistant_service', level='WARNING') as cm:
                assistant_service.answer("harmless question", request_id="test-request-id-3")

        combined = "\n".join(cm.output)
        self.assertIn("test-request-id-3", combined)
        self.assertIn("exception_type=ProviderAPIError", combined)
        self.assertNotIn("sensitive internal detail", combined)


if __name__ == '__main__':
    unittest.main()
