"""Tests for backend/mock_provider.py.

No network access, no API key, nothing to mock - this module is already
entirely self-contained and deterministic.
"""
import unittest

from backend import mock_provider


class MockProviderTest(unittest.TestCase):
    def test_generate_reply_returns_a_non_empty_string(self):
        result = mock_provider.generate_reply("What is a balanced diet?")
        self.assertIsInstance(result, str)
        self.assertTrue(result.strip())

    def test_generate_reply_is_clearly_labeled_as_a_mock(self):
        result = mock_provider.generate_reply("What is a balanced diet?")
        self.assertIn("mock", result.lower())

    def test_generate_reply_never_raises(self):
        # Should not raise regardless of input, including edge cases.
        mock_provider.generate_reply("")
        mock_provider.generate_reply("anything at all")
        mock_provider.generate_reply("hello", system="a system prompt")

    def test_generate_reply_accepts_the_same_signature_as_claude_provider(self):
        # Positional prompt + optional keyword-only `system`, matching
        # claude_provider.generate_reply exactly.
        result = mock_provider.generate_reply("hello", system="be concise")
        self.assertIsInstance(result, str)

    def test_generate_reply_is_deterministic(self):
        first = mock_provider.generate_reply("What is a balanced diet?")
        second = mock_provider.generate_reply("What is a balanced diet?")
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
