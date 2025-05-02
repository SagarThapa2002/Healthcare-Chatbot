import json
import os
from flask import Blueprint, request, jsonify

webhook_bp = Blueprint('webhook', __name__)

@webhook_bp.route('/webhook', methods=['POST'])
def webhook():
    try:
        req = request.get_json(force=True)
        print("Received JSON:", req)

        intent = req.get('queryResult', {}).get('intent', {}).get('displayName', '')

        if intent == "Symptom Check":
            symptom = req.get('queryResult', {}).get('parameters', {}).get('symptom')
            if symptom:
                response = f"You mentioned {symptom}. It's best to monitor your condition and consult a doctor if it gets worse."
            else:
                response = "Could you please tell me your symptom?"

        elif intent == "Book Appointment":
            parameters = req.get('queryResult', {}).get('parameters', {})
            print("Booking appointment with parameters:", parameters)
            name = parameters.get('name', 'the patient')
            date = parameters.get('date', 'a suitable date')
            time = parameters.get('time', 'a suitable time')

            appointment = {
                "name": name,
                "date": date,
                "time": time
            }

            file_path = os.path.join(os.path.dirname(__file__), 'appointments.json')

            # Load existing appointments safely
            appointments = []
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r') as f:
                        appointments = json.load(f)
                except json.JSONDecodeError:
                    print("Warning: appointments.json is empty or invalid, starting fresh.")
                    appointments = []

            appointments.append(appointment)
            with open(file_path, 'w') as f:
                json.dump(appointments, f, indent=2)

            response = f"Appointment booked for {name} on {date} at {time}."

        else:
            response = "Sorry, I didn't understand that."

        return jsonify({'fulfillmentText': response})

    except Exception as e:
        print("Webhook error:", str(e))
        return jsonify({'fulfillmentText': "Oops, something went wrong on the server."})


# ✅ New route to fetch all appointments
@webhook_bp.route('/appointments', methods=['GET'])
def get_appointments():
    file_path = os.path.join(os.path.dirname(__file__), 'appointments.json')

    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                appointments = json.load(f)
        except json.JSONDecodeError:
            appointments = []
    else:
        appointments = []

    return jsonify(appointments)
