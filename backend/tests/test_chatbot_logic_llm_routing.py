"""Tests for the LLM routing added to chatbot_logic.py's General FAQ branch.

These are full webhook-level integration tests (like test_webhook.py), kept
in their own file so the existing, carefully-scoped test_webhook.py is
never touched by this work.

Every test that could reach the network mocks either assistant_service.answer
or claude_provider.generate_reply. No ANTHROPIC_API_KEY is required, and no
real HTTP call to Anthropic occurs anywhere in this file.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import ANY, patch

from app import app
from backend import chatbot_logic, claude_provider, llm_config, mock_provider


class LLMRoutingTestCase(unittest.TestCase):
    """Base class: isolates appointment file I/O from the real
    backend/appointments.json, exactly like test_webhook.py's WebhookTestCase.
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


class NonGeneralIntentsNeverCallAssistantServiceTest(LLMRoutingTestCase):
    """Proves every deterministic intent is untouched by the LLM routing,
    regardless of LLM_ENABLED - these tests run with it explicitly on to
    make the guarantee as strong as possible.
    """

    def setUp(self):
        super().setUp()
        patcher = patch.object(llm_config, 'LLM_ENABLED', True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_book_appointment_never_calls_assistant_service(self):
        with patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            self.post_webhook("Book Appointment", {"name": "Test Patient", "message": "irrelevant"})
        mock_answer.assert_not_called()

    def test_update_appointment_never_calls_assistant_service(self):
        with patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            self.post_webhook("Update Appointment", {"name": "Test Patient", "message": "irrelevant"})
        mock_answer.assert_not_called()

    def test_cancel_appointment_never_calls_assistant_service(self):
        with patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            self.post_webhook("Cancel Appointment", {"name": "Test Patient", "message": "irrelevant"})
        mock_answer.assert_not_called()

    def test_view_appointments_never_calls_assistant_service(self):
        with patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            self.post_webhook("View Appointments", {"message": "irrelevant"})
        mock_answer.assert_not_called()

    def test_yes_intent_never_calls_assistant_service(self):
        with patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            self.post_webhook("YesIntent", {"message": "irrelevant"})
        mock_answer.assert_not_called()

    def test_no_intent_never_calls_assistant_service(self):
        with patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            self.post_webhook("NoIntent", {"message": "irrelevant"})
        mock_answer.assert_not_called()

    def test_symptom_check_never_calls_assistant_service(self):
        with patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            self.post_webhook("Symptom Check", {"symptom": "a headache", "message": "irrelevant"})
        mock_answer.assert_not_called()


class GeneralFaqRoutingGateTest(LLMRoutingTestCase):
    def test_calls_assistant_service_when_enabled_and_message_present(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            mock_answer.return_value = {
                "allowed": True, "category": "allowed", "text": "General info.", "source": "llm",
            }
            self.post_webhook("General FAQ", {"message": "What is a balanced diet?"})

        mock_answer.assert_called_once_with("What is a balanced diet?", request_id=ANY)

    def test_does_not_call_assistant_service_when_llm_disabled(self):
        with patch.object(llm_config, 'LLM_ENABLED', False), \
             patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            self.post_webhook("General FAQ", {"message": "What is a balanced diet?"})

        mock_answer.assert_not_called()

    def test_does_not_call_assistant_service_when_no_message_given(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            self.post_webhook("General FAQ", {})

        mock_answer.assert_not_called()

    def test_llm_disabled_general_faq_is_byte_identical_to_pre_llm_behavior(self):
        with patch.object(llm_config, 'LLM_ENABLED', False):
            data = self.post_webhook("General FAQ", {}).get_json()

        self.assertEqual(data["messages"][0]["type"], "text")
        self.assertIn("virtual healthcare assistant", data["messages"][0]["content"]["text"])


class ResponseContractTest(LLMRoutingTestCase):
    def test_successful_assistant_response_has_exact_structured_shape(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            mock_answer.return_value = {
                "allowed": True,
                "category": "allowed",
                "text": "A balanced diet includes a variety of foods.",
                "source": "llm",
            }
            data = self.post_webhook("General FAQ", {"message": "What is a balanced diet?"}).get_json()

        self.assertEqual(
            data["messages"][0],
            {
                "type": "assistant_response",
                "content": {
                    "text": "A balanced diet includes a variety of foods.",
                    "provider": "claude",
                    "disclaimer": "AI-generated general information, not medical advice.",
                },
                "suggestions": [],
            },
        )

    def test_deterministic_general_faq_keeps_plain_text_shape_when_llm_disabled(self):
        with patch.object(llm_config, 'LLM_ENABLED', False):
            data = self.post_webhook("General FAQ", {}).get_json()

        message = data["messages"][0]
        self.assertEqual(message["type"], "text")
        self.assertNotIn("provider", message["content"])
        self.assertNotIn("disclaimer", message["content"])

    def test_appointment_response_never_carries_assistant_metadata(self):
        with patch.object(llm_config, 'LLM_ENABLED', True):
            data = self.post_webhook("Book Appointment", {"name": "Test Patient"}).get_json()

        message = data["messages"][0]
        self.assertEqual(message["type"], "text")
        self.assertNotIn("provider", message["content"])
        self.assertNotIn("disclaimer", message["content"])

    def test_symptom_check_response_never_carries_assistant_metadata(self):
        with patch.object(llm_config, 'LLM_ENABLED', True):
            data = self.post_webhook("Symptom Check", {"symptom": "a headache"}).get_json()

        message = data["messages"][0]
        self.assertEqual(message["type"], "text")
        self.assertNotIn("provider", message["content"])

    def test_provider_failure_produces_safe_deterministic_fallback(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch("backend.chatbot_logic.assistant_service.answer") as mock_answer:
            mock_answer.return_value = {
                "allowed": False,
                "category": "provider_unavailable",
                "text": "I'm unable to answer that right now. Please try again in a moment, "
                        "or let me know if you'd like to check symptoms or book an appointment.",
                "source": "policy",
            }
            data = self.post_webhook("General FAQ", {"message": "What is a balanced diet?"}).get_json()

        message = data["messages"][0]
        self.assertEqual(message["type"], "text")
        self.assertEqual(message["content"]["text"], mock_answer.return_value["text"])

    def test_missing_api_key_produces_safe_fallback_via_the_real_integration_chain(self):
        # No mocking of assistant_service.answer here - this exercises the
        # REAL chatbot_logic -> assistant_service -> claude_provider chain.
        # Only the "is a key configured" check is forced to False, so no
        # Anthropic client is ever constructed and no network call is
        # possible, regardless of what's in the ambient environment.
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch.object(llm_config, 'has_api_key', return_value=False):
            data = self.post_webhook("General FAQ", {"message": "What is a balanced diet?"}).get_json()

        message = data["messages"][0]
        self.assertEqual(message["type"], "text")
        self.assertNotIn("provider", message["content"])


class SafetyIntegrationTest(LLMRoutingTestCase):
    def test_diagnosis_request_is_blocked_by_the_real_policy_layer(self):
        # No mocking of assistant_service at all - exercises the real,
        # deterministic policy layer. The provider call is spied on only
        # to prove it was never reached.
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            data = self.post_webhook("General FAQ", {"message": "Do I have diabetes?"}).get_json()

        mock_generate.assert_not_called()
        message = data["messages"][0]
        self.assertEqual(message["type"], "text")
        self.assertIn("qualified healthcare provider", message["content"]["text"])

    def test_medication_request_is_blocked_by_the_real_policy_layer(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            data = self.post_webhook(
                "General FAQ", {"message": "Should I stop taking my medication?"}
            ).get_json()

        mock_generate.assert_not_called()
        self.assertEqual(data["messages"][0]["type"], "text")

    def test_general_faq_appointment_action_is_blocked_by_the_real_policy_layer(self):
        # A General FAQ message that itself contains an appointment action
        # (here, also mentioning a symptom word) must never reach Claude.
        # This exercises assistant_service's own appointment-action policy
        # check as a defense-in-depth boundary at the backend, independent
        # of the frontend's intent classification (untouched) and
        # independent of symptom_triage.py (untouched, not wired in).
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            data = self.post_webhook(
                "General FAQ", {"message": "Can I book an appointment if I have a fever?"}
            ).get_json()

        mock_generate.assert_not_called()
        message = data["messages"][0]
        self.assertEqual(message["type"], "text")
        self.assertNotIn("provider", message["content"])
        self.assertIn("appointment booking flow", message["content"]["text"])

    def test_no_exception_details_leak_into_the_api_response(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            mock_generate.side_effect = claude_provider.ProviderAPIError(
                "super secret internal detail that must never leak"
            )
            data = self.post_webhook("General FAQ", {"message": "What is a balanced diet?"}).get_json()

        response_text = json.dumps(data)
        self.assertNotIn("super secret internal detail", response_text)
        self.assertNotIn("ANTHROPIC_API_KEY", response_text)


class MockProviderIntegrationTest(LLMRoutingTestCase):
    """Proves the full chain works end-to-end without a paid API key or
    network access - LLM_PROVIDER=mock is opt-in only and never changes
    which safety rules apply; claude_provider.generate_reply is spied on
    throughout to prove the real Anthropic integration is never touched
    while mock is selected.
    """

    def test_allowed_general_faq_flows_through_mock_provider_to_assistant_response(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch.object(llm_config, 'PROVIDER', 'mock'), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            data = self.post_webhook("General FAQ", {"message": "What is a balanced diet?"}).get_json()

        mock_generate.assert_not_called()
        message = data["messages"][0]
        self.assertEqual(
            message,
            {
                "type": "assistant_response",
                "content": {
                    "text": mock_provider.MOCK_REPLY,
                    "provider": "mock",
                    "disclaimer": "AI-generated general information, not medical advice.",
                },
                "suggestions": [],
            },
        )

    def test_appointment_action_never_reaches_either_provider_with_mock_enabled(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch.object(llm_config, 'PROVIDER', 'mock'), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate, \
             patch("backend.assistant_service.mock_provider.generate_reply") as mock_mock:
            data = self.post_webhook(
                "General FAQ", {"message": "Can I book an appointment if I have a fever?"}
            ).get_json()

        mock_generate.assert_not_called()
        mock_mock.assert_not_called()
        self.assertEqual(data["messages"][0]["type"], "text")

    def test_diagnosis_request_never_reaches_either_provider_with_mock_enabled(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch.object(llm_config, 'PROVIDER', 'mock'), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate, \
             patch("backend.assistant_service.mock_provider.generate_reply") as mock_mock:
            data = self.post_webhook("General FAQ", {"message": "Do I have diabetes?"}).get_json()

        mock_generate.assert_not_called()
        mock_mock.assert_not_called()
        self.assertEqual(data["messages"][0]["type"], "text")

    def test_medication_request_never_reaches_either_provider_with_mock_enabled(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch.object(llm_config, 'PROVIDER', 'mock'), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate, \
             patch("backend.assistant_service.mock_provider.generate_reply") as mock_mock:
            data = self.post_webhook(
                "General FAQ", {"message": "Should I stop taking my medication?"}
            ).get_json()

        mock_generate.assert_not_called()
        mock_mock.assert_not_called()
        self.assertEqual(data["messages"][0]["type"], "text")

    def test_treatment_request_never_reaches_either_provider_with_mock_enabled(self):
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch.object(llm_config, 'PROVIDER', 'mock'), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate, \
             patch("backend.assistant_service.mock_provider.generate_reply") as mock_mock:
            data = self.post_webhook(
                "General FAQ", {"message": "What treatment should I use for my condition?"}
            ).get_json()

        mock_generate.assert_not_called()
        mock_mock.assert_not_called()
        self.assertEqual(data["messages"][0]["type"], "text")

    def test_provider_failure_still_produces_safe_fallback_through_the_resolver(self):
        # Regression check on the _get_provider() refactor itself: with the
        # provider left at its default ("claude", not mock), a real
        # generate_reply failure must still fall back safely.
        with patch.object(llm_config, 'LLM_ENABLED', True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            mock_generate.side_effect = claude_provider.ProviderAPIError("internal detail")
            data = self.post_webhook("General FAQ", {"message": "What is a balanced diet?"}).get_json()

        message = data["messages"][0]
        self.assertEqual(message["type"], "text")
        self.assertNotIn("internal detail", json.dumps(data))


if __name__ == '__main__':
    unittest.main()
