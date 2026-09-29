"""Tests for app.py's debug/CORS configuration (API/security baseline).

Covers the two parsing functions (_parse_debug_flag/_parse_allowed_origins)
directly - pure, deterministic, no environment/network dependency - plus a
small integration check that the already-imported `app` object's live
CORS configuration actually behaves as those functions say it should for
the default (no env override) case. No real server is ever started:
FlaskDebugEnvironmentTest runs app.py's `python app.py` block in a
subprocess with werkzeug's run_simple replaced, only to record the debug
settings app.run() would use.
"""
import logging
import os
import subprocess
import sys
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
        # For `python app.py`'s development server, a malformed/unexpected
        # value must never accidentally enable debug mode - only the exact
        # "true" spelling does. (Flask's own reading of FLASK_DEBUG for the
        # imported app is looser - see FlaskDebugEnvironmentTest below.)
        for value in ("1", "yes", "on", "false", "TRUE ish", "0"):
            with self.subTest(value=value):
                self.assertFalse(_parse_debug_flag(value))


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Imports app (as Gunicorn does), records app.debug, then runs app.py's own
# `python app.py` block with werkzeug's run_simple replaced, so no server
# ever starts, and records the debug settings app.run() would have used.
_DEBUG_PROBE = """
import logging, runpy
from unittest.mock import patch
logging.disable(logging.CRITICAL)
import app
imported = app.app.debug
captured = {}
def fake_run_simple(host, port, application, **options):
    captured.update(options, debug=application.debug)
with patch("werkzeug.serving.run_simple", fake_run_simple):
    runpy.run_path("app.py", run_name="__main__")
print("RESULT", imported, captured["debug"], captured["use_debugger"])
"""


class FlaskDebugEnvironmentTest(unittest.TestCase):
    """Documents how FLASK_DEBUG actually behaves on both startup paths.

    FLASK_DEBUG is read once, when the app is created, so each case runs
    in a fresh subprocess with only that variable changed - nothing leaks
    into this test process or other tests.
    """

    def _probe(self, value):
        env = {k: v for k, v in os.environ.items() if k != "FLASK_DEBUG"}
        if value is not None:
            env["FLASK_DEBUG"] = value
        env["PYTHONPATH"] = REPO_ROOT
        result = subprocess.run(
            [sys.executable, "-c", _DEBUG_PROBE],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        line = [l for l in result.stdout.splitlines() if l.startswith("RESULT ")][-1]
        imported, dev_debug, dev_debugger = line.split()[1:]
        return {
            "imported_app_debug": imported == "True",
            "dev_server_debug": dev_debug == "True",
            "dev_server_debugger": dev_debugger == "True",
        }

    def test_unset_disables_debug_on_both_paths(self):
        self.assertEqual(
            self._probe(None),
            {"imported_app_debug": False, "dev_server_debug": False, "dev_server_debugger": False},
        )

    def test_false_disables_debug_on_both_paths(self):
        self.assertEqual(
            self._probe("false"),
            {"imported_app_debug": False, "dev_server_debug": False, "dev_server_debugger": False},
        )

    def test_true_enables_debug_on_both_paths(self):
        self.assertEqual(
            self._probe("true"),
            {"imported_app_debug": True, "dev_server_debug": True, "dev_server_debugger": True},
        )

    def test_one_enables_flask_debug_for_the_imported_app_but_not_python_app_py(self):
        # Under Gunicorn the imported app is what serves requests, so
        # FLASK_DEBUG=1 turns Flask's debug mode on in a deployment.
        self.assertEqual(
            self._probe("1"),
            {"imported_app_debug": True, "dev_server_debug": False, "dev_server_debugger": False},
        )

    def test_yes_enables_flask_debug_for_the_imported_app_but_not_python_app_py(self):
        self.assertEqual(
            self._probe("yes"),
            {"imported_app_debug": True, "dev_server_debug": False, "dev_server_debugger": False},
        )


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

    def test_wildcard_is_rejected(self):
        # flask_cors would treat "*" as "allow every origin".
        with self.assertRaises(ValueError):
            _parse_allowed_origins("*")

    def test_regex_character_typo_is_rejected(self):
        # flask_cors would regex prefix-match this, also allowing
        # "https://app.example.co.evil.com".
        with self.assertRaises(ValueError):
            _parse_allowed_origins("https://app.example.com?")

    def test_any_regex_character_is_rejected(self):
        for char in '*\\?$^[]()':
            with self.subTest(char=char):
                with self.assertRaises(ValueError):
                    _parse_allowed_origins(f"https://app{char}.example.invalid")

    def test_one_bad_entry_in_a_list_rejects_the_whole_value(self):
        # Never silently drop the bad entry and carry on with the rest.
        with self.assertRaises(ValueError):
            _parse_allowed_origins("http://localhost:3000, https://*.example.invalid")


class CorsDefaultBehaviorTest(unittest.TestCase):
    """Integration-level: exercises the actual, already-configured `app`
    object (module import time, with no CORS_ALLOWED_ORIGINS override in
    this test process's environment) through a real test client request,
    rather than only the parsing functions above.

    Redirects chatbot_logic.APPOINTMENTS_FILE to an empty temp directory
    for the duration of each test - matching test_webhook.py's own
    isolation convention - so the real backend/appointments.json (which
    holds genuine bookings) is never read by any test in this class. Only
    GET and OPTIONS (preflight) requests are made here, so this is a
    belt-and-braces isolation choice, not a correctness requirement.
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

    def test_allowed_origin_preflight_is_granted(self):
        response = self.client.options('/webhook/webhook', headers={
            'Origin': DEFAULT_DEV_ORIGIN,
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), DEFAULT_DEV_ORIGIN)
        self.assertIn('POST', response.headers.get('Access-Control-Allow-Methods', ''))
        self.assertIn('content-type', response.headers.get('Access-Control-Allow-Headers', '').lower())

    def test_private_network_access_is_not_granted_to_an_allowed_origin(self):
        # CVE-2024-6221: Flask-Cors 4.0.0 answered this preflight with
        # Access-Control-Allow-Private-Network: true by default. The app
        # never opts into private network access.
        response = self.client.options('/webhook/webhook', headers={
            'Origin': DEFAULT_DEV_ORIGIN,
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Private-Network': 'true',
        })
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), DEFAULT_DEV_ORIGIN)
        self.assertNotEqual(response.headers.get('Access-Control-Allow-Private-Network'), 'true')

    def test_crlf_in_request_path_cannot_forge_a_flask_cors_log_line(self):
        # CVE-2024-1681: with DEBUG logging, Flask-Cors 4.0.0 logged the
        # decoded request path verbatim, so %0d%0a in the URL started a
        # new, attacker-controlled log line.
        records = []

        class Collect(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        cors_logger = logging.getLogger('flask_cors')
        handler = Collect()
        previous_level = cors_logger.level
        cors_logger.addHandler(handler)
        cors_logger.setLevel(logging.DEBUG)
        try:
            self.client.get(
                '/webhook/providers%0d%0aFORGED-LOG-LINE', headers={'Origin': DEFAULT_DEV_ORIGIN}
            )
        finally:
            cors_logger.removeHandler(handler)
            cors_logger.setLevel(previous_level)

        self.assertTrue(records, "expected Flask-Cors to log this request at DEBUG")
        for message in records:
            self.assertNotIn('\n', message)
            self.assertNotIn('\r', message)


if __name__ == '__main__':
    unittest.main()
