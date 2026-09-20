# 🏥 Healthcare Chatbot for Primary Care and Appointment Scheduling

A healthcare chatbot system that provides basic symptom checks and allows patients to book appointments using natural language. Intent detection currently happens directly in the React frontend; the Flask backend's webhook contract mirrors the Dialogflow ES fulfillment format but Dialogflow itself is not wired in at runtime. See `dialogflow/README.md` for a hand-authored Dialogflow ES scaffold matching that contract.

---

## 📘 Final Year Project – CN6000  
****

**Created by:** Sagar Thapa  
**Module:** CN6000 - Final Year Project  


---

## 🧠 Project Description

This project demonstrates a healthcare chatbot that:

- Accepts symptom-related queries and provides basic advice
- Enables patients to book an appointment with a doctor
- Performs intent detection in the frontend via keyword/pattern matching (`frontend/src/conversation/intent.js`); the backend webhook contract mirrors the Dialogflow ES fulfillment format, but Dialogflow is not currently wired in at runtime (see `dialogflow/README.md`)
- Has a Flask-based backend for webhook logic
- Stores booked appointments in a local JSON file
- Exposes an API endpoint to view all booked appointments
- Includes a deterministic, rule-based symptom-triage module (`backend/symptom_triage.py`) that is fully implemented and tested but not yet connected to the live chatbot, and whose production rule file currently contains zero active (clinically reviewed) rules - see `backend/SYMPTOM_RULES_SOURCES.md`

---

## 💡 Features

- **Symptom Checker**  
  Users can say things like:  
  `I have a headache` or `I'm feeling dizzy`.

- **Appointment Booking**  
  Users can book appointments with utterances like:  
  `I want to book an appointment for John on May 5th at 10am`.

- **Appointment Storage**  
  All appointments are stored in `appointments.json`.

- **API to View Appointments**  
  Access booked appointments via GET request to `/webhook/appointments`.

---

## ⚙️ Technologies Used

- **Dialogflow ES** – webhook contract only (see `dialogflow/README.md`); not wired in at runtime
- **Python 3**
- **Flask**
- **Ngrok** – previously used for tunneling localhost to a live Dialogflow agent; not required for the current setup
- **Git/GitHub** – for version control

---

## 🛠️ Installation & Setup

### Prerequisites

- Python 3.x
- Pip
- Ngrok
- Git

### Clone the Repository

```bash
git clone https://github.com/your-username/healthcare-chatbot.git
cd healthcare-chatbot/backend
pip install -r requirements.txt
python app.py
ngrok http 5000
