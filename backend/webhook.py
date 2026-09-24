import logging

from flask import Blueprint, request, jsonify

from backend import reminder_service, response_model
from backend.chatbot_logic import handle_webhook_request, list_appointments

logger = logging.getLogger(__name__)

webhook_bp = Blueprint('webhook', __name__)


@webhook_bp.route('/webhook', methods=['POST'])
def webhook():
    # Exactly one request_id per request, generated up front so it is
    # available to the failure path too. Never log the raw payload here -
    # see backend/LOGGING_NOTES.md for exactly what is/isn't logged.
    request_id = response_model.new_request_id()
    try:
        payload = request.get_json(force=True)
        logger.info("webhook request received request_id=%s", request_id)

        result = handle_webhook_request(payload, request_id=request_id)
        logger.info(
            "webhook request completed request_id=%s intent=%s success=%s",
            request_id,
            (result.get("context") or {}).get("intent"),
            result.get("success"),
        )
        return jsonify(result)

    except Exception as e:
        logger.error(
            "webhook request failed request_id=%s exception_type=%s",
            request_id, type(e).__name__,
        )
        return jsonify(response_model.error_response(
            "Oops, something went wrong on the server.", request_id=request_id
        ))


@webhook_bp.route('/appointments', methods=['GET'])
def get_appointments():
    return jsonify(list_appointments())


@webhook_bp.route('/reminders', methods=['GET'])
def get_reminders():
    # Read-only - mirrors get_appointments() above exactly. Returns the
    # raw reminder record array as-is: reminder_service.list_reminders()
    # already tolerates a missing/malformed reminders.json by returning
    # [] (see its own docstring), so there is no new failure mode here to
    # handle. Reminder records carry no patient-identifying content (no
    # name/date/time - those stay in appointments.json, referenced only
    # by an opaque appointmentId), so this is no more sensitive than the
    # existing /appointments endpoint above - if anything, less so.
    return jsonify(reminder_service.list_reminders())
