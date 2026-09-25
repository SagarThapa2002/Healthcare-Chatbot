"""Tests for app.py's debug/CORS configuration (API/security baseline).

Covers the two parsing functions (_parse_debug_flag/_parse_allowed_origins)
directly - pure, deterministic, no environment/network dependency - plus a
small integration check that the already-imported `app` object's live
CORS configuration actually behaves as those functions say it should for
the default (no env override) case. Debug mode itself is never exercised
via a real app.run() call anywhere in this file (that would start a real
server) - only the parsing function that decides its value.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from app import app, DEFAULT_DEV_ORIGIN, _parse_allowed_origins, _parse_debug_flag
from backend import chatbot_logic


class ParseDebugFlagTest(unittest.TestCase):
    def test_unset_defaults_to_false(self):
        self.assertFalse(_parse_debug_flag(None))

    def test_blank_is_false(self):
        self.assertFalse(_parse_debug_flag(""))
        self.assertFalse(_parse_debug_flag("   "))

    def test_exact_true_enables_it(self):
        self.assertTrue(_parse_debug_flag("true"))

    def test_case_and_whitespace_insensitive(self):
        self.assertTrue(_parse_debug_flag("True"))
        self.assertTrue(_parse_debug_flag("TRUE"))
        self.assertTrue(_parse_debug_flag("  true  "))

    def test_malformed_or_unexpected_values_fail_safe_to_false(self):
        # A malformed/unexpected value must never accidentally enable
        # debug mode - only the exact "true" spelling does.
        for value in ("1", "yes", "on", "false", "TRUE ish", "0"):
            with self.subTest(value=value):
                self.assertFalse(_parse_debug_flag(value))


class ParseAllowedOriginsTest(unittest.TestCase):
    def test_unset_falls_back_to_default_dev_origin(self):
        self.assertEqual(_parse_allowed_origins(None), [DEFAULT_DEV_ORIGIN])

    def test_blank_falls_back_to_default_dev_origin(self):
        self.assertEqual(_parse_allowed_origins(""), [DEFAULT_DEV_ORIGIN])
        self.assertEqual(_parse_allowed_origins("   "), [DEFAULT_DEV_ORIGIN])

    def test_only_commas_and_whitespace_falls_back_to_default(self):
        # No non-empty entry survives parsing - must not silently resolve
        # to an empty allow-list (which would break local development)
        # or be misinterpreted some other way.
        self.assertEqual(_parse_allowed_origins(",, ,"), [DEFAULT_DEV_ORIGIN])

    def test_single_configured_origin(self):
        self.assertEqual(
            _parse_allowed_origins("https://example.invalid"), ["https://example.invalid"]
        )

    def test_multiple_comma_separated_origins_are_trimmed(self):
        self.assertEqual(
            _parse_allowed_origins(" http://localhost:3000 , https://example.invalid "),
            ["http://localhost:3000", "https://example.invalid"],
        )


class CorsDefaultBehaviorTest(unittest.TestCase):
    """Integration-level: exercises the actual, already-configured `app`
    object (module import time, with no CORS_ALLOWED_ORIGINS override in
    this test process's environment) through a real test client request,
    rather than only the parsing functions above.

    Redirects chatbot_logic.APPOINTMENTS_FILE to an empty temp directory
    for the duration of each test - matching test_webhook.py's own
    isolation convention - so the real backend/appointments.json (which
    holds genuine bookings) is never read by any test in this class. Only
    GET requests are made here, so this is a belt-and-braces isolation
    choice, not a correctness requirement.
    """

    def setUp(self):
        self.client = app.test_client()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        patcher = patch.object(
            chatbot_logic, 'APPOINTMENTS_FILE', os.path.join(self.tmp_dir.name, 'appointments.json')
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_configured_frontend_origin_is_allowed(self):
        response = self.client.get('/webhook/appointments', headers={'Origin': DEFAULT_DEV_ORIGIN})
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), DEFAULT_DEV_ORIGIN)

    def test_an_unconfigured_arbitrary_origin_is_not_allowed(self):
        response = self.client.get(
            '/webhook/appointments', headers={'Origin': 'https://not-configured.example.invalid'}
        )
        self.assertNotEqual(
            response.headers.get('Access-Control-Allow-Origin'), 'https://not-configured.example.invalid'
        )

    def test_no_origin_header_still_serves_the_request_normally(self):
        # CORS restriction must never block a same-origin/non-browser
        # request (no Origin header at all) - only cross-origin browser
        # requests ever consult Access-Control-Allow-Origin.
        response = self.client.get('/webhook/appointments')
        self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
