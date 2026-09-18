from flask import Blueprint, request, jsonify

from backend import response_model
from backend.chatbot_logic import handle_webhook_request, list_appointments

webhook_bp = Blueprint('webhook', __name__)


@webhook_bp.route('/webhook', methods=['POST'])
def webhook():
    try:
        payload = request.get_json(force=True)
        print("Received JSON:", payload)

        result = handle_webhook_request(payload)
        return jsonify(result)

    except Exception as e:
        print("Webhook error:", str(e))
        return jsonify(response_model.error_response("Oops, something went wrong on the server."))


@webhook_bp.route('/appointments', methods=['GET'])
def get_appointments():
    return jsonify(list_appointments())
