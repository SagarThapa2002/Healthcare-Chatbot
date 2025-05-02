from flask import Blueprint, request, jsonify

webhook_bp = Blueprint('webhook', __name__)

@webhook_bp.route('/webhook', methods=['POST'])  # <-- make sure this matches your ngrok URL
def webhook():
    try:
        req = request.get_json(force=True)
        print("Received JSON:", req)  # Log to terminal

        intent = req.get('queryResult', {}).get('intent', {}).get('displayName', '')

        if intent == "Symptom Check":
            symptom = req.get('queryResult', {}).get('parameters', {}).get('symptom')
            if symptom:
                response = f"You mentioned {symptom}. It's best to monitor your condition and consult a doctor if it gets worse."
            else:
                response = "Could you please tell me your symptom?"

        elif intent == "Book Appointment":
            parameters = req.get('queryResult', {}).get('parameters', {})
            name = parameters.get('name', 'the patient')
            date = parameters.get('date', 'a suitable date')
            time = parameters.get('time', 'a suitable time')
            response = f"Appointment booked for {name} on {date} at {time}."

        else:
            response = "Sorry, I didn't understand that."

        return jsonify({'fulfillmentText': response})

    except Exception as e:
        print("Webhook error:", str(e))
        return jsonify({'fulfillmentText': "Oops, something went wrong on the server."})
