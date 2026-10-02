import logging

from flask import Blueprint, request, jsonify
from werkzeug.exceptions import RequestEntityTooLarge

from backend import provider_repository, reminder_service, response_model
from backend.chatbot_logic import (
    handle_webhook_request, owned_appointments, parse_owner_token, public_appointment,
)

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

        result = handle_webhook_request(
            payload, request_id=request_id, owner_token=request.headers.get('X-Owner-Token')
        )
        logger.info(
            "webhook request completed request_id=%s intent=%s success=%s",
            request_id,
            (result.get("context") or {}).get("intent"),
            result.get("success"),
        )
        return jsonify(result)

    except RequestEntityTooLarge:
        # The body exceeded app.config["MAX_CONTENT_LENGTH"] (see app.py).
        # Still HTTP 200, like every other webhook response, with its own
        # error code so a client can tell it apart from a server failure.
        logger.warning("webhook request rejected request_id=%s reason=request_too_large", request_id)
        return jsonify(response_model.error_response(
            "Request body is too large.", code="REQUEST_TOO_LARGE", request_id=request_id
        ))

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
    # Only the active appointments owned by this request's X-Owner-Token -
    # [] without a valid token. ownerId is internal and never returned (see
    # public_appointment).
    owner = parse_owner_token(request.headers.get('X-Owner-Token'))
    return jsonify([
        public_appointment(a) for a in owned_appointments(owner) if a.get('status') != 'cancelled'
    ])


@webhook_bp.route('/reminders', methods=['GET'])
def get_reminders():
    # Read-only. Returns only the reminders for appointments owned by this
    # request's X-Owner-Token (any appointment status), as stored - [] without
    # a valid token. A reminder's sendAt reveals its appointment's time, so it
    # is scoped like the appointment itself. reminder_service.list_reminders()
    # already tolerates a missing/malformed reminders.json by returning [].
    owner = parse_owner_token(request.headers.get('X-Owner-Token'))
    owned_ids = {a.get('id') for a in owned_appointments(owner) if a.get('id')}
    return jsonify([r for r in reminder_service.list_reminders() if r.get('appointmentId') in owned_ids])


@webhook_bp.route('/providers', methods=['GET'])
def get_providers():
    # Read-only - mirrors get_appointments()/get_reminders() above. Unlike
    # those two, provider_repository.list_providers() does NOT tolerate a
    # missing/malformed providers.json - it raises ProviderDataError (see
    # provider_repository.py's own "fail loudly, never silently guess"
    # convention, matching symptom_triage.py's identical policy). That is
    # deliberately left to propagate here rather than caught and papered
    # over with an empty list: providers.json is core reference data (not
    # incidental per-request records like appointments/reminders), so a
    # corrupt file should be a loud, visible failure, not a silently empty
    # provider list. Provider records carry no patient-identifying content
    # (id/name/specialty/location only), so this is no more sensitive than
    # the existing /appointments and /reminders routes above.
    return jsonify(provider_repository.list_providers())
