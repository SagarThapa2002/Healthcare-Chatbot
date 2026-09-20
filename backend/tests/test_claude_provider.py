"""Tests for backend/claude_provider.py.

Every test mocks the Anthropic SDK client entirely. No real network call is
made anywhere in this file, and no ANTHROPIC_API_KEY needs to be set in the
environment for these tests to pass.
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic as real_anthropic

from backend import claude_provider, llm_config


def fake_text_response(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


class ProviderConstructionTest(unittest.TestCase):
    def test_importing_the_module_does_not_require_network_or_a_key(self):
        # If importing claude_provider made a network call or required a
        # real key, this test file would already have failed/hung before
        # reaching any test body - the import happened at module load.
        self.assertTrue(hasattr(claude_provider, "generate_reply"))

    def test_missing_api_key_raises_config_error_without_touching_anthropic(self):
        with patch.object(llm_config, "has_api_key", return_value=False), \
             patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            with self.assertRaises(claude_provider.ProviderConfigError):
                claude_provider.generate_reply("hello")
            MockAnthropic.assert_not_called()

    def test_api_key_is_obtained_from_configuration(self):
        with patch.object(llm_config, "has_api_key", return_value=True), \
             patch.object(llm_config, "get_api_key", return_value="test-key-123"), \
             patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            MockAnthropic.return_value.messages.create.return_value = fake_text_response("hi")

            claude_provider.generate_reply("hello")

            _, kwargs = MockAnthropic.call_args
            self.assertEqual(kwargs["api_key"], "test-key-123")


class GenerateReplyTest(unittest.TestCase):
    def setUp(self):
        patcher_has_key = patch.object(llm_config, "has_api_key", return_value=True)
        patcher_get_key = patch.object(llm_config, "get_api_key", return_value="test-key-123")
        patcher_has_key.start()
        patcher_get_key.start()
        self.addCleanup(patcher_has_key.stop)
        self.addCleanup(patcher_get_key.stop)

    def test_successful_mocked_response_becomes_plain_text(self):
        with patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            MockAnthropic.return_value.messages.create.return_value = fake_text_response(
                "General health information here."
            )

            result = claude_provider.generate_reply("What is a balanced diet?")

            self.assertEqual(result, "General health information here.")

    def test_no_automatic_retries_and_explicit_timeout_are_configured(self):
        with patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            MockAnthropic.return_value.messages.create.return_value = fake_text_response("ok")

            claude_provider.generate_reply("hello")

            _, kwargs = MockAnthropic.call_args
            self.assertEqual(kwargs["max_retries"], 0)
            self.assertEqual(kwargs["timeout"], llm_config.TIMEOUT_SECONDS)

    def test_model_and_max_tokens_come_from_config_not_hardcoded_business_logic(self):
        with patch.object(llm_config, "MODEL", "test-model-name"), \
             patch.object(llm_config, "MAX_TOKENS", 77), \
             patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = fake_text_response("ok")

            claude_provider.generate_reply("hello")

            _, kwargs = mock_client.messages.create.call_args
            self.assertEqual(kwargs["model"], "test-model-name")
            self.assertEqual(kwargs["max_tokens"], 77)

    def test_no_conversation_history_only_the_single_prompt_is_sent(self):
        with patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = fake_text_response("ok")

            claude_provider.generate_reply("hello")

            _, kwargs = mock_client.messages.create.call_args
            self.assertEqual(kwargs["messages"], [{"role": "user", "content": "hello"}])

    def test_system_prompt_passed_through_when_given(self):
        with patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = fake_text_response("ok")

            claude_provider.generate_reply("hello", system="Be concise.")

            _, kwargs = mock_client.messages.create.call_args
            self.assertEqual(kwargs["system"], "Be concise.")

    def test_no_system_kwarg_sent_when_not_given(self):
        with patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.return_value = fake_text_response("ok")

            claude_provider.generate_reply("hello")

            _, kwargs = mock_client.messages.create.call_args
            self.assertNotIn("system", kwargs)

    def test_empty_content_list_raises_response_error(self):
        with patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            MockAnthropic.return_value.messages.create.return_value = SimpleNamespace(content=[])

            with self.assertRaises(claude_provider.ProviderResponseError):
                claude_provider.generate_reply("hello")

    def test_blank_text_content_raises_response_error(self):
        with patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            MockAnthropic.return_value.messages.create.return_value = fake_text_response("   ")

            with self.assertRaises(claude_provider.ProviderResponseError):
                claude_provider.generate_reply("hello")

    def test_non_text_content_raises_response_error(self):
        with patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            MockAnthropic.return_value.messages.create.return_value = SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", text=None)]
            )

            with self.assertRaises(claude_provider.ProviderResponseError):
                claude_provider.generate_reply("hello")

    def test_timeout_is_converted_to_a_typed_provider_error(self):
        with patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.side_effect = real_anthropic.APITimeoutError(
                request=MagicMock()
            )

            with self.assertRaises(claude_provider.ProviderTimeoutError):
                claude_provider.generate_reply("hello")

    def test_generic_api_status_error_is_converted_to_a_typed_provider_error(self):
        with patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.side_effect = real_anthropic.APIStatusError(
                "boom", response=mock_response, body=None
            )

            with self.assertRaises(claude_provider.ProviderAPIError):
                claude_provider.generate_reply("hello")

    def test_authentication_error_is_converted_to_a_typed_provider_error(self):
        with patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.side_effect = real_anthropic.AuthenticationError(
                "invalid key", response=mock_response, body=None
            )

            with self.assertRaises(claude_provider.ProviderAPIError):
                claude_provider.generate_reply("hello")

    def test_connection_error_is_converted_to_a_typed_provider_error(self):
        with patch("backend.claude_provider.anthropic.Anthropic") as MockAnthropic:
            mock_client = MockAnthropic.return_value
            mock_client.messages.create.side_effect = real_anthropic.APIConnectionError(
                request=MagicMock()
            )

            with self.assertRaises(claude_provider.ProviderAPIError):
                claude_provider.generate_reply("hello")


if __name__ == '__main__':
    unittest.main()
