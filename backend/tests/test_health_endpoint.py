"""Tests for the GET /health deployment health check in app.py.

/health loads and validates the provider reference data through
provider_repository's own loaders and reports only "ok" (200) or
"unavailable" (503). It must never read or write runtime data files
(appointments, reminders, pending state), never call the LLM, and never
expose ProviderDataError's message - which contains absolute file paths -
in either the response or the logs.
"""
import builtins
import os
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import (
    assistant_service,
    availability_service,
    chatbot_logic,
    provider_repository,
    reminder_service,
)

SECRET_DETAIL = "providers file not found: /very/secret/path/providers.json"


class HealthEndpointTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_real_provider_data_reports_ok(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/json')
        self.assertEqual(response.get_json(), {"status": "ok"})

    def test_load_providers_failure_reports_unavailable(self):
        with patch.object(
            provider_repository, 'load_providers',
            side_effect=provider_repository.ProviderDataError(SECRET_DETAIL),
        ):
            response = self.client.get('/health')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.mimetype, 'application/json')
        self.assertEqual(response.get_json(), {"status": "unavailable"})

    def test_load_availability_failure_reports_unavailable(self):
        with patch.object(
            provider_repository, 'load_availability',
            side_effect=provider_repository.ProviderDataError(SECRET_DETAIL),
        ):
            response = self.client.get('/health')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"status": "unavailable"})

    def test_invalid_real_file_reports_unavailable(self):
        # End to end through the real loader's validation, not a mock.
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, 'providers.json')
            with open(bad, 'w') as f:
                f.write('{"not": "a list"}')
            with patch.object(provider_repository, 'PROVIDERS_FILE', bad):
                response = self.client.get('/health')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"status": "unavailable"})

    def test_failure_response_does_not_expose_exception_details(self):
        with patch.object(
            provider_repository, 'load_providers',
            side_effect=provider_repository.ProviderDataError(SECRET_DETAIL),
        ):
            response = self.client.get('/health')
        body = response.get_data(as_text=True)
        self.assertNotIn("secret", body)
        self.assertNotIn("providers.json", body)
        self.assertNotIn("not found", body)

    def test_failure_logs_only_the_exception_type(self):
        with patch.object(
            provider_repository, 'load_providers',
            side_effect=provider_repository.ProviderDataError(SECRET_DETAIL),
        ):
            with self.assertLogs('app', level='WARNING') as logs:
                self.client.get('/health')
        self.assertEqual(
            logs.output, ["WARNING:app:health check failed exception_type=ProviderDataError"]
        )
        self.assertNotIn("secret", "\n".join(logs.output))

    def test_success_does_not_log_a_warning(self):
        with patch('app.logger') as mock_logger:
            self.client.get('/health')
        mock_logger.warning.assert_not_called()

    def test_runtime_data_files_are_not_opened_created_or_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_paths = {
                (chatbot_logic, 'APPOINTMENTS_FILE'): os.path.join(tmp, 'appointments.json'),
                (chatbot_logic, 'PENDING_FILE'): os.path.join(tmp, 'pending_appointments.json'),
                (chatbot_logic, 'PENDING_CANCELLATION_FILE'): os.path.join(tmp, 'pending_cancellation.json'),
                (chatbot_logic, 'PENDING_UPDATE_FILE'): os.path.join(tmp, 'pending_update.json'),
                (availability_service, 'APPOINTMENTS_FILE'): os.path.join(tmp, 'appointments.json'),
                (reminder_service, 'REMINDERS_FILE'): os.path.join(tmp, 'reminders.json'),
                (reminder_service, 'APPOINTMENTS_FILE'): os.path.join(tmp, 'appointments.json'),
            }
            # Each runtime file exists (as an empty JSON array), so any code
            # path that reads one would actually open it - a missing file is
            # skipped via os.path.exists() without ever being opened.
            for path in set(runtime_paths.values()):
                with open(path, 'w') as f:
                    f.write('[]')
            before = {name: os.path.getmtime(os.path.join(tmp, name)) for name in os.listdir(tmp)}

            patchers = [patch.object(module, name, path) for (module, name), path in runtime_paths.items()]
            for patcher in patchers:
                patcher.start()
                self.addCleanup(patcher.stop)

            real_open = builtins.open
            with patch('builtins.open', side_effect=real_open) as spy_open:
                response = self.client.get('/health')

            self.assertEqual(response.status_code, 200)
            opened = {os.path.abspath(call.args[0]) for call in spy_open.call_args_list}
            self.assertEqual(
                opened,
                {
                    os.path.abspath(provider_repository.PROVIDERS_FILE),
                    os.path.abspath(provider_repository.AVAILABILITY_FILE),
                },
            )
            after = {name: os.path.getmtime(os.path.join(tmp, name)) for name in os.listdir(tmp)}
            self.assertEqual(after, before)
            for name in after:
                with open(os.path.join(tmp, name)) as f:
                    self.assertEqual(f.read(), '[]')

    def test_llm_is_never_invoked(self):
        with patch.object(assistant_service, 'answer') as mock_answer:
            response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        mock_answer.assert_not_called()

    def test_head_health_succeeds_with_an_empty_body(self):
        response = self.client.head('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(), b"")

    def test_root_endpoint_is_unchanged(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"message": "Healthcare Chatbot API is running."})


if __name__ == '__main__':
    unittest.main()
