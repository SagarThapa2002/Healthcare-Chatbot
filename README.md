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
```

---

## 🔔 Appointment Reminders

The backend includes a deterministic appointment-reminder subsystem (Phase 6.2). It is functional but **not automatic** and **not connected to any real notification provider** - see the limitations below before assuming this sends real reminders to anyone.

### What creates and updates reminders

- **A successful new booking** can create one pending `24h_before` reminder for that appointment, if it is eligible (see below).
- **A date/time-changing appointment update** cancels the appointment's old pending reminder (if any) and creates a fresh one for the new date/time, if eligible.
- **An appointment cancellation** cancels its pending reminder. Reminders are never deleted, only transitioned to a terminal status (`cancelled`), preserving history.

A reminder's `sendAt` is calculated from the appointment's **clinic-local** date/time, then converted and stored as **UTC**. The clinic's timezone is configured via the `CLINIC_TIMEZONE` environment variable (an IANA name, e.g. `Europe/London`) - there is no default, and reminder scheduling fails safely (without affecting the appointment itself) if it is missing or invalid.

**Legacy appointments without a stable id are not eligible for a reminder** - a reminder needs a stable foreign key to reference, and older records (predating appointment ids) have none.

### Processing due reminders (manual only)

Due reminders are **not** processed automatically. Processing them requires manually running:

```bash
python -m backend.run_due_reminders
```

- `--dry-run` performs a read-only check of how many reminders are currently due, without processing or mutating anything.
- `--now <ISO-8601 timestamp>` (e.g. `--now 2027-06-02T00:00:00+00:00`) overrides the "current instant" used for due-detection, for deterministic manual testing or demonstration.

### Notification delivery

The only notification provider currently available is a deterministic, local **mock** provider, selected by setting:

```bash
NOTIFICATION_PROVIDER=mock
```

The mock provider **never sends a real notification of any kind** - no network call, no email, no SMS. It exists solely to exercise and demonstrate the due-reminder processing pipeline end-to-end. Without `NOTIFICATION_PROVIDER=mock` set, the CLI refuses to process reminders at all, rather than doing nothing silently.

### Viewing reminders

```
GET /webhook/reminders
```

Returns the current reminder records for development/demo visibility. **This endpoint only reads and reports existing reminder state - it does not process, send, or otherwise act on reminders itself.**

### Current limitations

This subsystem is intentionally scoped and should not be mistaken for a production-ready reminder service:

- **No automatic scheduler or background worker** - nothing invokes `run_due_reminders` on its own; it must be run manually (or by an external trigger you set up yourself).
- **No real email/SMS/push notification provider** - only the local mock exists.
- **No retry policy** - a `failed` reminder is a terminal outcome; it is never automatically retried.
- **At-least-once, not exactly-once, delivery semantics** - if the process crashes after a notification is sent but before that outcome is saved, the next run may attempt to send it again.
- **No file locking or concurrent-invocation protection** - only one invocation of `run_due_reminders` should run at a time.
