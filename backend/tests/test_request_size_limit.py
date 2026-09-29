"""Tests for the request-body size limit (app.py's MAX_CONTENT_LENGTH) and
backend/webhook.py's handling of it.

An oversized POST /webhook/webhook body is rejected before it is parsed:
the response is the existing error envelope with code REQUEST_TOO_LARGE,
still HTTP 200 like every other webhook response, and nothing from the
body is echoed back or written to disk. All data files are redirected to a
temp directory, matching test_webhook.py's WebhookTestCase isolation.
"""
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import availability_service, chatbot_logic, reminder_service

LIMIT = 64 * 1024
FULL_BOOKING = {"providerId": "dr-patel", "date": "2026-12-28", "time": "10:00"}


def webhook_body(name, **parameters):
    return json.dumps({
        "queryResult": {
            "intent": {"displayName": "Book Appointment"},
            "parameters": {"name": name, **parameters},
        }
    }).encode()


def body_of_exact_size(size):
    """A Book Appointment body exactly `size` bytes long."""
    overhead = len(webhook_body(""))
    return webhook_body("x" * (size - overhead))


class RequestSizeLimitTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        tmp = self.tmp_dir.name
        paths = [
            (chatbot_logic, 'APPOINTMENTS_FILE', 'appointments.json'),
            (chatbot_logic, 'PENDING_FILE', 'pending_appointments.json'),
            (chatbot_logic, 'PENDING_CANCELLATION_FILE', 'pending_cancellation.json'),
            (chatbot_logic, 'PENDING_UPDATE_FILE', 'pending_update.json'),
            (availability_service, 'APPOINTMENTS_FILE', 'appointments.json'),
            (reminder_service, 'APPOINTMENTS_FILE', 'appointments.json'),
            (reminder_service, 'REMINDERS_FILE', 'reminders.json'),
        ]
        for module, attribute, filename in paths:
            patcher = patch.object(module, attribute, os.path.join(tmp, filename))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.test_client()

    def post_body(self, body):
        return self.client.post('/webhook/webhook', data=body, content_type='application/json')

    def written_files(self):
        return sorted(os.listdir(self.tmp_dir.name))

    def test_limit_is_configured_as_64_kb(self):
        self.assertEqual(app.config["MAX_CONTENT_LENGTH"], 64 * 1024)

    def test_request_below_the_limit_takes_the_normal_webhook_path(self):
        response = self.post_body(webhook_body("Normal Patient"))
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["context"]["bookingStage"], "provider")

    def test_request_of_exactly_the_limit_is_accepted(self):
        body = body_of_exact_size(LIMIT)
        self.assertEqual(len(body), LIMIT)
        data = self.post_body(body).get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["context"]["bookingStage"], "provider")

    def test_oversized_request_returns_http_200(self):
        response = self.post_body(body_of_exact_size(LIMIT + 1))
        self.assertEqual(response.status_code, 200)

    def test_oversized_request_uses_the_existing_error_envelope(self):
        data = self.post_body(body_of_exact_size(LIMIT + 1)).get_json()
        self.assertEqual(set(data), {"success", "error", "messages", "context", "meta"})
        self.assertFalse(data["success"])
        self.assertEqual(data["messages"], [])
        self.assertIsNone(data["context"])
        self.assertEqual(data["meta"]["schemaVersion"], "1.0")
        self.assertTrue(data["meta"]["requestId"])

    def test_oversized_request_error_code_and_message(self):
        data = self.post_body(body_of_exact_size(LIMIT + 1)).get_json()
        self.assertEqual(
            data["error"], {"code": "REQUEST_TOO_LARGE", "message": "Request body is too large."}
        )

    def test_oversized_request_body_is_not_echoed(self):
        response = self.post_body(body_of_exact_size(LIMIT + 1))
        self.assertNotIn("xxxxxxxxxx", response.get_data(as_text=True))
        self.assertLess(len(response.get_data()), 1024)

    def test_oversized_request_writes_no_appointment_or_pending_state(self):
        # Control: the same full booking below the limit does reach the
        # confirm stage and write pending state, so the check below is
        # meaningful.
        small = self.post_body(webhook_body("Small", **FULL_BOOKING)).get_json()
        self.assertEqual(small["context"]["bookingStage"], "confirm")
        self.assertEqual(self.written_files(), ["pending_appointments.json"])
        os.remove(os.path.join(self.tmp_dir.name, "pending_appointments.json"))

        padding = "x" * (LIMIT + 1)
        data = self.post_body(webhook_body(padding, **FULL_BOOKING)).get_json()
        self.assertEqual(data["error"]["code"], "REQUEST_TOO_LARGE")
        self.assertEqual(self.written_files(), [])

    def test_oversized_request_logs_a_warning_without_the_payload(self):
        with self.assertLogs('backend.webhook', level='WARNING') as logs:
            data = self.post_body(body_of_exact_size(LIMIT + 1)).get_json()
        self.assertEqual(
            logs.output,
            [
                "WARNING:backend.webhook:webhook request rejected "
                f"request_id={data['meta']['requestId']} reason=request_too_large"
            ],
        )

    def test_unrelated_exceptions_still_return_internal_error(self):
        with patch('backend.webhook.handle_webhook_request', side_effect=RuntimeError("boom")):
            data = self.post_body(webhook_body("Normal Patient")).get_json()
        self.assertFalse(data["success"])
        self.assertEqual(
            data["error"],
            {"code": "INTERNAL_ERROR", "message": "Oops, something went wrong on the server."},
        )

    def test_invalid_json_below_the_limit_still_returns_internal_error(self):
        response = self.post_body(b"{not json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["error"]["code"], "INTERNAL_ERROR")

    def test_oversized_body_without_content_length_is_still_rejected_and_bounded(self):
        # A chunked body with no Content-Length (as Gunicorn passes it) is
        # cut off at the limit by Werkzeug rather than rejected up front, so
        # the truncated JSON fails to parse. The error code depends on the
        # Werkzeug version; what matters is that it is rejected, nothing is
        # echoed, and nothing is written.
        body = webhook_body("x" * (LIMIT + 1024), **FULL_BOOKING)
        response = self.client.post(
            '/webhook/webhook',
            input_stream=io.BytesIO(body),
            content_type='application/json',
            environ_overrides={"wsgi.input_terminated": True, "CONTENT_LENGTH": ""},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertFalse(data["success"])
        self.assertIn(data["error"]["code"], {"REQUEST_TOO_LARGE", "INTERNAL_ERROR"})
        self.assertNotIn("xxxxxxxxxx", response.get_data(as_text=True))
        self.assertEqual(self.written_files(), [])

    def test_health_and_get_endpoints_are_unaffected(self):
        self.assertEqual(self.client.get('/health').get_json(), {"status": "ok"})
        self.assertEqual(self.client.get('/').status_code, 200)
        for path in ('/webhook/appointments', '/webhook/providers', '/webhook/reminders'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIsInstance(response.get_json(), list)


if __name__ == '__main__':
    unittest.main()
