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

        file_path = os.path.join(os.path.dirname(__file__), 'appointments.json')
        pending_path = os.path.join(os.path.dirname(__file__), 'pending_appointments.json')

        if intent == "Symptom Check":
            symptom = req.get('queryResult', {}).get('parameters', {}).get('symptom')
            if symptom:
                response = f"Thanks for sharing. Since you're experiencing {symptom}, I recommend keeping an eye on it. If it worsens, please consider visiting a healthcare provider."
            else:
                response = "Could you please tell me your symptom so I can assist you better?"

        elif intent == "Book Appointment":
            parameters = req.get('queryResult', {}).get('parameters', {})
            name = parameters.get('name')
            date = parameters.get('date')
            time = parameters.get('time')

            if not name:
                response = "Sure, may I have your name for the appointment?"
            elif not date:
                response = f"Thanks {name}. What date would you prefer for your appointment?"
            elif not time:
                response = f"Got it, {name} wants an appointment on {date}. What time would you like?"
            else:
                pending = {
                    "name": name,
                    "date": date,
                    "time": time
                }
                with open(pending_path, 'w') as f:
                    json.dump(pending, f, indent=2)
                response = f"Please confirm — book appointment for {name} on {date} at {time}? (yes or no)"

        elif intent == "YesIntent":
            if os.path.exists(pending_path):
                with open(pending_path, 'r') as f:
                    appointment = json.load(f)

                appointments = []
                if os.path.exists(file_path):
                    try:
                        with open(file_path, 'r') as f:
                            appointments = json.load(f)
                    except json.JSONDecodeError:
                        appointments = []

                appointments.append(appointment)
                with open(file_path, 'w') as f:
                    json.dump(appointments, f, indent=2)
                os.remove(pending_path)

                response = f"Your appointment for {appointment['name']} on {appointment['date']} at {appointment['time']} has been booked."
            else:
                response = "There is no appointment pending confirmation."

        elif intent == "NoIntent":
            if os.path.exists(pending_path):
                os.remove(pending_path)
                response = "No problem! Appointment booking has been canceled. Let me know if you'd like to try again."
            else:
                response = "There is no pending appointment to cancel."

        elif intent == "Update Appointment":
            parameters = req.get('queryResult', {}).get('parameters', {})
            name = parameters.get('name')
            new_date = parameters.get('date')
            new_time = parameters.get('time')

            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    appointments = json.load(f)

                updated = False
                for appointment in appointments:
                    if appointment['name'].lower() == name.lower():
                        if new_date:
                            appointment['date'] = new_date
                        if new_time:
                            appointment['time'] = new_time
                        updated = True
                        break

                if updated:
                    with open(file_path, 'w') as f:
                        json.dump(appointments, f, indent=2)
                    response = f"Your appointment for {name} has been updated."
                else:
                    response = f"I couldn't find an appointment for {name}."
            else:
                response = "There are no appointments to update yet."

        elif intent == "Cancel Appointment":
            parameters = req.get('queryResult', {}).get('parameters', {})
            name = parameters.get('name')

            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    appointments = json.load(f)

                original_length = len(appointments)
                appointments = [a for a in appointments if a['name'].lower() != name.lower()]

                with open(file_path, 'w') as f:
                    json.dump(appointments, f, indent=2)

                if len(appointments) < original_length:
                    response = f"Your appointment for {name} has been successfully canceled."
                else:
                    response = f"I couldn't find an appointment for {name} to cancel."
            else:
                response = "There are no appointments to cancel yet."

        elif intent == "View Appointments":
            if os.path.exists(file_path):
                try:
                    with open(file_path, 'r') as f:
                        appointments = json.load(f)
                    if appointments:
                        response_lines = [f"{a['name']} on {a['date']} at {a['time']}" for a in appointments]
                        response = "Here’s a quick look at your scheduled appointments:\n" + "\n".join(response_lines)
                    else:
                        response = "You don't have any appointments booked at the moment."
                except json.JSONDecodeError:
                    response = "I'm having trouble reading your appointment records right now."
            else:
                response = "No appointment data found."

        elif intent == "General FAQ":
            response = (
                "Hi! I'm your virtual healthcare assistant. I can help you check symptoms, "
                "book or cancel appointments, and answer general health-related questions. "
                "What would you like help with today?"
            )

        else:
            response = "Sorry, I didn't understand that. Could you rephrase or ask something else?"

        return jsonify({'fulfillmentText': response})

    except Exception as e:
        print("Webhook error:", str(e))
        return jsonify({'fulfillmentText': "Oops, something went wrong on the server."})


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
