"""Application/service logic for the healthcare chatbot.

This is the same per-intent logic that used to live inline in webhook.py,
relocated so webhook.py can stay a thin HTTP adapter. Behavior is
preserved exactly, including a couple of pre-existing inconsistencies in
how corrupt appointments.json is handled between branches (see
_handle_update_appointment / _handle_cancel_appointment vs _handle_yes_intent
and _handle_view_appointments below) - those are carried over unchanged,
not "fixed", since fixing them wasn't asked for in this phase.
"""
import json
import os

from backend import response_model

APPOINTMENTS_FILE = os.path.join(os.path.dirname(__file__), 'appointments.json')
PENDING_FILE = os.path.join(os.path.dirname(__file__), 'pending_appointments.json')


def _read_appointments_raw():
    with open(APPOINTMENTS_FILE, 'r') as f:
        return json.load(f)


def _save_appointments(appointments):
    with open(APPOINTMENTS_FILE, 'w') as f:
        json.dump(appointments, f, indent=2)


def list_appointments():
    if not os.path.exists(APPOINTMENTS_FILE):
        return []
    try:
        return _read_appointments_raw()
    except json.JSONDecodeError:
        return []


def handle_webhook_request(payload):
    query_result = payload.get('queryResult', {})
    intent = query_result.get('intent', {}).get('displayName', '')
    parameters = query_result.get('parameters', {})

    if intent == "Symptom Check":
        messages = _handle_symptom_check(parameters)
    elif intent == "Book Appointment":
        messages = _handle_book_appointment(parameters)
    elif intent == "YesIntent":
        messages = _handle_yes_intent()
    elif intent == "NoIntent":
        messages = _handle_no_intent()
    elif intent == "Update Appointment":
        messages = _handle_update_appointment(parameters)
    elif intent == "Cancel Appointment":
        messages = _handle_cancel_appointment(parameters)
    elif intent == "View Appointments":
        messages = _handle_view_appointments()
    elif intent == "General FAQ":
        messages = _handle_general_faq()
    else:
        messages = [response_model.text_message(
            "Sorry, I didn't understand that. Could you rephrase or ask something else?"
        )]

    return response_model.success_response(messages, intent=intent)


def _handle_symptom_check(parameters):
    symptom = parameters.get('symptom')
    if symptom:
        text = f"Thanks for sharing. Since you're experiencing {symptom}, I recommend keeping an eye on it. If it worsens, please consider visiting a healthcare provider."
    else:
        text = "Could you please tell me your symptom so I can assist you better?"
    return [response_model.text_message(text)]


def _handle_book_appointment(parameters):
    name = parameters.get('name')
    date = parameters.get('date')
    time = parameters.get('time')

    if not name:
        text = "Sure, may I have your name for the appointment?"
    elif not date:
        text = f"Thanks {name}. What date would you prefer for your appointment?"
    elif not time:
        text = f"Got it, {name} wants an appointment on {date}. What time would you like?"
    else:
        pending = {
            "name": name,
            "date": date,
            "time": time
        }
        with open(PENDING_FILE, 'w') as f:
            json.dump(pending, f, indent=2)
        text = f"Please confirm — book appointment for {name} on {date} at {time}? (yes or no)"

    return [response_model.text_message(text)]


def _handle_yes_intent():
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, 'r') as f:
            appointment = json.load(f)

        appointments = []
        if os.path.exists(APPOINTMENTS_FILE):
            try:
                appointments = _read_appointments_raw()
            except json.JSONDecodeError:
                appointments = []

        appointments.append(appointment)
        _save_appointments(appointments)
        os.remove(PENDING_FILE)

        text = f"Your appointment for {appointment['name']} on {appointment['date']} at {appointment['time']} has been booked."
        return [response_model.booking_confirmation_message(text, appointment)]

    text = "There is no appointment pending confirmation."
    return [response_model.text_message(text)]


def _handle_no_intent():
    if os.path.exists(PENDING_FILE):
        os.remove(PENDING_FILE)
        text = "No problem! Appointment booking has been canceled. Let me know if you'd like to try again."
    else:
        text = "There is no pending appointment to cancel."
    return [response_model.text_message(text)]


def _handle_update_appointment(parameters):
    name = parameters.get('name')
    new_date = parameters.get('date')
    new_time = parameters.get('time')

    if os.path.exists(APPOINTMENTS_FILE):
        appointments = _read_appointments_raw()

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
            _save_appointments(appointments)
            text = f"Your appointment for {name} has been updated."
        else:
            text = f"I couldn't find an appointment for {name}."
    else:
        text = "There are no appointments to update yet."

    return [response_model.text_message(text)]


def _handle_cancel_appointment(parameters):
    name = parameters.get('name')

    if os.path.exists(APPOINTMENTS_FILE):
        appointments = _read_appointments_raw()

        original_length = len(appointments)
        appointments = [a for a in appointments if a['name'].lower() != name.lower()]
        _save_appointments(appointments)

        if len(appointments) < original_length:
            text = f"Your appointment for {name} has been successfully canceled."
        else:
            text = f"I couldn't find an appointment for {name} to cancel."
    else:
        text = "There are no appointments to cancel yet."

    return [response_model.text_message(text)]


def _handle_view_appointments():
    if os.path.exists(APPOINTMENTS_FILE):
        try:
            appointments = _read_appointments_raw()
            if appointments:
                response_lines = [f"{a['name']} on {a['date']} at {a['time']}" for a in appointments]
                text = "Here’s a quick look at your scheduled appointments:\n" + "\n".join(response_lines)
            else:
                text = "You don't have any appointments booked at the moment."
        except json.JSONDecodeError:
            text = "I'm having trouble reading your appointment records right now."
    else:
        text = "No appointment data found."

    return [response_model.text_message(text)]


def _handle_general_faq():
    text = (
        "Hi! I'm your virtual healthcare assistant. I can help you check symptoms, "
        "book or cancel appointments, and answer general health-related questions. "
        "What would you like help with today?"
    )
    return [response_model.text_message(text)]
