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
        parameters = req.get('queryResult', {}).get('parameters', {})

        file_path = os.path.join(os.path.dirname(__file__), 'appointments.json')

        if intent == "Symptom Check":
            symptom = parameters.get('symptom')
            if symptom:
                response = f"You mentioned {symptom}. It's best to monitor your condition and consult a doctor if it gets worse."
            else:
                response = "Could you please tell me your symptom?"

        elif intent == "Book Appointment":
            name = parameters.get('name', 'the patient')
            date = parameters.get('date', 'a suitable date')
            time = parameters.get('time', 'a suitable time')

            appointment = { "name": name, "date": date, "time": time }

            appointments = []
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r') as f:
                        appointments = json.load(f)
                except json.JSONDecodeError:
                    print("Warning: appointments.json is empty or invalid.")

            appointments.append(appointment)
            with open(file_path, 'w') as f:
                json.dump(appointments, f, indent=2)

            response = f"Appointment booked for {name} on {date} at {time}."

        elif intent == "View Appointments":
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r') as f:
                        appointments = json.load(f)
                    if appointments:
                        lines = [f"{a['name']} on {a['date']} at {a['time']}" for a in appointments]
                        response = "Here are your appointments:\n" + "\n".join(lines)
                    else:
                        response = "There are no appointments booked yet."
                except json.JSONDecodeError:
                    response = "Appointment records are currently unavailable."
            else:
                response = "No appointment data found."

        elif intent == "Update Appointment":
            name = parameters.get('name')
            date = parameters.get('date')
            time = parameters.get('time')

            updated = False
            appointments = []
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    appointments = json.load(f)

                for appt in appointments:
                    if appt['name'].lower() == name.lower():
                        appt['date'] = date
                        appt['time'] = time
                        updated = True
                        break

                with open(file_path, 'w') as f:
                    json.dump(appointments, f, indent=2)

            if updated:
                response = f"Updated appointment for {name} to {date} at {time}."
            else:
                response = f"No appointment found for {name} to update."

        elif intent == "Cancel Appointment":
            name = parameters.get('name')

            appointments = []
            canceled = False
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    appointments = json.load(f)

                new_appointments = [a for a in appointments if a['name'].lower() != name.lower()]
                canceled = len(new_appointments) < len(appointments)

                with open(file_path, 'w') as f:
                    json.dump(new_appointments, f, indent=2)

            if canceled:
                response = f"Appointment for {name} has been canceled."
            else:
                response = f"No appointment found for {name} to cancel."

        elif intent == "General FAQ":
            response = "I'm your healthcare assistant. I can help you check symptoms, book appointments, or answer general questions."

        else:
            response = "Sorry, I didn't understand that."

        return jsonify({'fulfillmentText': response})

    except Exception as e:
        print("Webhook error:", str(e))
        return jsonify({'fulfillmentText': "Oops, something went wrong on the server."})

# ✅ API to view appointments (for development/testing)
@webhook_bp.route('/appointments', methods=['GET'])
def get_appointments():
    file_path = os.path.join(os.path.dirname(__file__), 'appointments.json')
    appointments = []
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                appointments = json.load(f)
        except json.JSONDecodeError:
            appointments = []
    return jsonify(appointments)
