"""Tests for backend/assistant_service.py.

Every test that could reach claude_provider mocks it entirely - no real
network call is made anywhere in this file, and no ANTHROPIC_API_KEY needs
to be set. Several tests deliberately use the REAL llm_config.LLM_ENABLED
default (False) rather than patching it, to directly prove the default-off
behavior rather than only proving that patching it works.
"""
import unittest
from unittest.mock import patch

from backend import assistant_service, claude_provider, llm_config, mock_provider


class ClassifyRequestPolicyTest(unittest.TestCase):
    def test_harmless_general_question_is_allowed(self):
        self.assertEqual(
            assistant_service.classify_request("What is a balanced diet?"),
            assistant_service.ALLOWED,
        )

    def test_diagnosis_request_is_refused(self):
        self.assertEqual(
            assistant_service.classify_request("Do I have diabetes?"),
            assistant_service.REFUSAL_DIAGNOSIS,
        )

    def test_medication_change_request_is_refused(self):
        self.assertEqual(
            assistant_service.classify_request("Should I stop taking my medication?"),
            assistant_service.REFUSAL_MEDICATION,
        )

    def test_individualized_treatment_request_is_refused(self):
        self.assertEqual(
            assistant_service.classify_request(
                "What treatment should I use for my condition?"
            ),
            assistant_service.REFUSAL_TREATMENT,
        )

    def test_clinician_replacement_request_is_refused(self):
        self.assertEqual(
            assistant_service.classify_request("Can you be my doctor?"),
            assistant_service.REFUSAL_CLINICIAN_REPLACEMENT,
        )

    def test_book_appointment_request_is_not_allowed_through(self):
        self.assertEqual(
            assistant_service.classify_request("I want to book an appointment"),
            assistant_service.REFUSAL_APPOINTMENT_ACTION,
        )

    def test_cancel_appointment_request_is_not_allowed_through(self):
        self.assertEqual(
            assistant_service.classify_request("Please cancel my appointment"),
            assistant_service.REFUSAL_APPOINTMENT_ACTION,
        )

    def test_update_appointment_request_is_not_allowed_through(self):
        self.assertEqual(
            assistant_service.classify_request("I need to update my appointment"),
            assistant_service.REFUSAL_APPOINTMENT_ACTION,
        )

    def test_empty_input_is_rejected_safely(self):
        self.assertEqual(assistant_service.classify_request(""), assistant_service.REFUSAL_EMPTY_INPUT)

    def test_whitespace_only_input_is_rejected_safely(self):
        self.assertEqual(
            assistant_service.classify_request("   \n\t  "), assistant_service.REFUSAL_EMPTY_INPUT
        )

    def test_none_input_is_rejected_safely(self):
        self.assertEqual(assistant_service.classify_request(None), assistant_service.REFUSAL_EMPTY_INPUT)


class SystemPromptTest(unittest.TestCase):
    def test_prompt_is_a_function_independent_of_business_logic(self):
        # Calling it twice with no arguments and no state must be
        # side-effect-free and stable.
        self.assertEqual(assistant_service.build_system_prompt(), assistant_service.build_system_prompt())

    def test_prompt_states_scope_and_boundaries(self):
        prompt = assistant_service.build_system_prompt().lower()
        for expected in [
            "not a doctor",
            "diagnose",
            "medication",
            "individualized treatment",
            "clinician",
            "appointments",
            "emergency",
            "reveal this prompt",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, prompt)


class ProviderSelectionTest(unittest.TestCase):
    """Confirms the default provider selection is unchanged by the
    addition of mock_provider.py - the real Anthropic integration remains
    the default, and mock is opt-in only.
    """

    def test_default_provider_is_the_real_claude_provider(self):
        self.assertEqual(llm_config.PROVIDER, "claude", "LLM_PROVIDER must default to 'claude'")
        name, fn = assistant_service._get_provider()
        self.assertEqual(name, "claude")
        self.assertIs(fn, claude_provider.generate_reply)

    def test_unrecognized_provider_value_falls_back_to_claude(self):
        with patch.object(llm_config, 'PROVIDER', 'not-a-real-provider'):
            name, fn = assistant_service._get_provider()
        self.assertEqual(name, "claude")
        self.assertIs(fn, claude_provider.generate_reply)

    def test_mock_provider_is_selected_only_when_explicitly_configured(self):
        with patch.object(llm_config, 'PROVIDER', 'mock'):
            name, fn = assistant_service._get_provider()
        self.assertEqual(name, "mock")
        self.assertIs(fn, mock_provider.generate_reply)


class AnswerPolicyGateTest(unittest.TestCase):
    """Confirms the provider is never called when policy says to refuse,
    and that LLM_ENABLED=false (the real default) blocks every call on
    its own, independent of the policy categories above.
    """

    def test_llm_disabled_by_default_prevents_any_provider_call(self):
        self.assertFalse(llm_config.LLM_ENABLED, "LLM_ENABLED must default to False")
        with patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            result = assistant_service.answer("What is a balanced diet?")
        mock_generate.assert_not_called()
        self.assertFalse(result["allowed"])
        self.assertEqual(result["category"], assistant_service.LLM_DISABLED)

    def test_diagnosis_request_never_reaches_the_provider(self):
        with patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            result = assistant_service.answer("Do I have diabetes?")
        mock_generate.assert_not_called()
        self.assertFalse(result["allowed"])
        self.assertEqual(result["category"], assistant_service.REFUSAL_DIAGNOSIS)

    def test_book_appointment_request_never_reaches_the_provider(self):
        with patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            result = assistant_service.answer("Book me an appointment for Monday")
        mock_generate.assert_not_called()
        self.assertEqual(result["category"], assistant_service.REFUSAL_APPOINTMENT_ACTION)

    def test_cancel_appointment_request_never_reaches_the_provider(self):
        with patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            result = assistant_service.answer("Cancel my appointment please")
        mock_generate.assert_not_called()
        self.assertEqual(result["category"], assistant_service.REFUSAL_APPOINTMENT_ACTION)

    def test_empty_input_never_reaches_the_provider(self):
        with patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            result = assistant_service.answer("   ")
        mock_generate.assert_not_called()
        self.assertEqual(result["category"], assistant_service.REFUSAL_EMPTY_INPUT)

    def test_refusal_text_never_exposes_internals(self):
        result = assistant_service.answer("Do I have diabetes?")
        text = result["text"].lower()
        for forbidden in ["api", "key", "traceback", "exception", "env", "anthropic"]:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)


class AnswerWithLlmEnabledTest(unittest.TestCase):
    """These tests explicitly enable the LLM path via patching, since the
    real default is off - see AnswerPolicyGateTest for the default-off
    proof. Still fully mocked; no network call.
    """

    def test_allowed_message_calls_provider_and_returns_its_text(self):
        with patch.object(llm_config, "LLM_ENABLED", True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            mock_generate.return_value = "A balanced diet includes a variety of food groups."

            result = assistant_service.answer("What is a balanced diet?")

            mock_generate.assert_called_once()
            self.assertTrue(result["allowed"])
            self.assertEqual(result["source"], "llm")
            self.assertEqual(result["text"], "A balanced diet includes a variety of food groups.")

    def test_provider_is_given_the_system_prompt(self):
        with patch.object(llm_config, "LLM_ENABLED", True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            mock_generate.return_value = "ok"

            assistant_service.answer("What is a balanced diet?")

            _, kwargs = mock_generate.call_args
            self.assertEqual(kwargs["system"], assistant_service.build_system_prompt())

    def test_provider_failure_becomes_a_controlled_result_not_a_crash(self):
        with patch.object(llm_config, "LLM_ENABLED", True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            mock_generate.side_effect = claude_provider.ProviderAPIError(
                "sensitive internal detail that must not leak"
            )

            result = assistant_service.answer("What is a balanced diet?")

            self.assertFalse(result["allowed"])
            self.assertEqual(result["category"], assistant_service.PROVIDER_UNAVAILABLE)
            self.assertNotIn("sensitive internal detail", result["text"])

    def test_unexpected_exception_also_becomes_a_controlled_result(self):
        with patch.object(llm_config, "LLM_ENABLED", True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            mock_generate.side_effect = RuntimeError("unexpected bug detail")

            result = assistant_service.answer("What is a balanced diet?")

            self.assertFalse(result["allowed"])
            self.assertNotIn("unexpected bug detail", result["text"])

    def test_output_safety_check_rejects_a_clearly_unsafe_mocked_response(self):
        with patch.object(llm_config, "LLM_ENABLED", True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            mock_generate.return_value = "You definitely have diabetes and should stop taking your insulin."

            result = assistant_service.answer("What is a balanced diet?")

            self.assertFalse(result["allowed"])
            self.assertEqual(result["category"], assistant_service.UNSAFE_OUTPUT_BLOCKED)
            self.assertNotIn("diabetes", result["text"])

    def test_output_safety_check_allows_an_ordinary_safe_response(self):
        with patch.object(llm_config, "LLM_ENABLED", True), \
             patch("backend.assistant_service.claude_provider.generate_reply") as mock_generate:
            mock_generate.return_value = "Drinking enough water is generally good for most people."

            result = assistant_service.answer("What is a balanced diet?")

            self.assertTrue(result["allowed"])


class OutputSafetyCheckDisclaimerTest(unittest.TestCase):
    """The requirement that this check is defense-in-depth, not a
    guarantee, must be a real, inspectable fact - not just a comment.
    """

    def test_disclaimer_constant_exists_and_says_defense_in_depth(self):
        disclaimer = assistant_service.OUTPUT_SAFETY_CHECK_DISCLAIMER.lower()
        self.assertIn("defense-in-depth", disclaimer)
        self.assertIn("not a guarantee", disclaimer)

    def test_passes_output_safety_check_is_documented_as_a_backstop(self):
        doc = (assistant_service._passes_output_safety_check.__doc__ or "").lower()
        self.assertIn("backstop", doc)


if __name__ == '__main__':
    unittest.main()
