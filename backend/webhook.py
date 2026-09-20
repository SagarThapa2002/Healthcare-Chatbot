import logging

from flask import Blueprint, request, jsonify

from backend import response_model
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
