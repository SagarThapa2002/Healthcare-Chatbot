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

- **Chat Webhook**
  Chat messages are sent as `POST /webhook/webhook` - the blueprint's `/webhook` prefix combined with the route's own `/webhook` path.

- **Appointments View**
  A read-only Appointments tab in the frontend lists your active appointments (name, date, time, and provider when known). Booking, updating, and cancelling an appointment still happens through chat.

- **General Health Questions**
  An optional, disabled-by-default LLM-backed assistant can answer general health questions that don't match any other intent, controlled by the `LLM_ENABLED` environment variable. See `backend/LLM_ASSISTANT_NOTES.md` for details.

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

- Python 3.10+
- Pip
- Node.js & npm
- Ngrok (optional - see "Technologies Used" above)
- Git

### Clone the Repository

```bash
git clone https://github.com/your-username/healthcare-chatbot.git
cd healthcare-chatbot
```

### Backend Setup

`app.py` lives at the repository root and imports `backend.webhook`, so both
commands below must be run from the repository root - not from inside `backend/`:

```bash
pip install -r backend/requirements.txt
```

**Local development** - Flask's built-in development server, on `http://127.0.0.1:5000`:

```bash
python app.py
```

**Production** - [Gunicorn](https://gunicorn.org/) serving the same `app:app` application object:

```bash
gunicorn --workers 1 --bind 0.0.0.0:${PORT:-5000} app:app
```

- The server binds to `0.0.0.0` so it is reachable from outside its host or container. If your hosting platform assigns the port through a `PORT` environment variable, it is used; otherwise the port defaults to `5000`.
- **Run exactly one worker.** Appointments, reminders and in-progress bookings, cancellations and updates are stored in mutable JSON files on the local disk, and separate worker processes would not safely coordinate changes to them. This is an intentional limitation of the current file-based storage, not a recommendation for how the app should scale long-term.
- Point your hosting platform's health check at `GET /health`. It returns `200 {"status": "ok"}` when the provider reference data (`providers.json`, `provider_availability.json`) loads and validates, and `503 {"status": "unavailable"}` otherwise. It does not check that appointment data is being stored durably.
- Gunicorn does not run on Windows; use `python app.py` for local development there.
- A deployed frontend must be built with `REACT_APP_API_BASE_URL` pointing at this backend (see Frontend configuration below), and the backend's `CORS_ALLOWED_ORIGINS` must include the deployed frontend's origin (see Configuration).

Ngrok is not needed for either command (see "Technologies Used").

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `FLASK_DEBUG` | off (`false`) | Set to `true` to enable Flask's debug mode (interactive debugger, auto-reload) for local development only — never enable this outside your own machine. |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated list of origins allowed to call the API. Defaults to the local frontend dev server only; set this to your own frontend's origin(s) if it runs anywhere else. Must contain exact origins; wildcards and regex characters are rejected. |

### Frontend Setup

```bash
cd frontend
npm install
npm start
```

#### Frontend configuration

| Variable | Default | Purpose |
|---|---|---|
| `REACT_APP_API_BASE_URL` | `http://127.0.0.1:5000` | Base URL of the backend API that the frontend calls (e.g. `https://api.example.com`). Surrounding whitespace and trailing slashes are ignored; an unset or blank value falls back to the default. |

Create React App applies `REACT_APP_*` variables when `npm start` or `npm run build` runs, so they are fixed at build time: changing the value requires rebuilding the production frontend. For example:

```bash
cd frontend
REACT_APP_API_BASE_URL=https://api.example.com npm run build
```

The deployed frontend's origin must also be listed in the backend's `CORS_ALLOWED_ORIGINS` (see Configuration above), or the browser will block its requests.

**Never put secrets, passwords, API keys or credentials in `REACT_APP_*` variables** - they are bundled into the frontend JavaScript and readable by anyone who loads the page.

---

## 🚀 Deployment

> **This is a portfolio/demo deployment, not a production healthcare system.** Read [Data and safety notice](#data-and-safety-notice) before making it public.

The backend and frontend deploy separately to any host that can run a Python web service and serve static files. No platform-specific configuration is included or required. The runtime versions tested in CI are pinned in `.python-version` (Python 3.11) and `frontend/.nvmrc` (Node 24).

| | Backend | Frontend |
|---|---|---|
| Root directory | repository root | `frontend/` |
| Runtime | Python 3.11 | Node 24 |
| Install | `pip install -r backend/requirements.txt` | `npm ci` |
| Build | - | `REACT_APP_API_BASE_URL=https://<backend-url> npm run build` |
| Start / publish | `gunicorn --workers 1 --bind 0.0.0.0:${PORT:-5000} app:app` | publish `frontend/build/` |
| Health check | `GET /health` | - |

- **Backend:** run exactly one Gunicorn worker, because persistence is JSON-backed (see Backend Setup). `/health` confirms that the provider reference data loads and validates; it does **not** verify that appointment data is stored durably.
- **Frontend:** serve `frontend/build/` from the root of its domain (the built assets are referenced as `/static/...`). No rewrite rules are needed, because the app has no client-side router.

### Deployment order

1. Deploy the backend.
2. Configure the backend environment (see the table below).
3. Verify that `GET /health` returns `200 {"status": "ok"}`.
4. Note the backend's public URL.
5. Build and deploy the frontend with `REACT_APP_API_BASE_URL` set to that backend URL.
6. Set the backend's `CORS_ALLOWED_ORIGINS` to the frontend's deployed origin (e.g. `https://chat.example.com`, no trailing path), then restart the backend.
7. Open the deployed frontend and check that it can talk to the backend - for example, that the Appointments tab loads and a chat message gets a reply.

### Production environment variables

| Variable | Where | Status | Notes |
|---|---|---|---|
| `CORS_ALLOWED_ORIGINS` | backend | **required** | The deployed frontend's origin. If unset, only `http://localhost:3000` is allowed. |
| `PORT` | backend | required if your host supplies it | Used by the Gunicorn command; falls back to `5000`. |
| `REACT_APP_API_BASE_URL` | frontend build | **required** | The backend's public URL, applied at build time. If unset, the build calls `http://127.0.0.1:5000`. |
| `FLASK_DEBUG` | backend | **keep unset or `false`** | Enables Flask's debug mode; never enable it on a deployed server. Flask reads this variable itself, so it affects the app under Gunicorn too. |
| `LOG_LEVEL` | backend | optional | Default `INFO`. |
| `CLINIC_TIMEZONE` | backend | optional | IANA timezone (e.g. `Europe/London`); no default. Without it, bookings still work but no reminders are created. |
| `LLM_ENABLED` | backend | optional - **keep disabled for a public demo** | Default `false`. See the LLM note below. |
| `LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS`, `ANTHROPIC_TIMEOUT_SECONDS` | backend | optional | Only used when `LLM_ENABLED=true`; see `backend/LLM_ASSISTANT_NOTES.md`. |
| `NOTIFICATION_PROVIDER` | reminder CLI | optional | Only read by `python -m backend.run_due_reminders`; `mock` is the only provider. Not used by the web server. |

Set these through your host's environment-variable settings - `.env` files are not loaded by the backend.

**LLM:** the General Health Questions assistant is optional and disabled by default. The API has no authentication or rate limiting, so enabling it with a real `ANTHROPIC_API_KEY` on a public deployment lets anyone who can reach the site generate API usage billed to that key. Keep `LLM_ENABLED` unset or `false` for a public demo unless you intentionally accept that cost and exposure.

### Data and safety notice

- **Storage is local JSON files.** Appointments, reminders and in-progress conversation state are stored as JSON files in `backend/` on the server's local disk.
- **Restarts:** data survives a process restart only if the host preserves the disk. Hosts that replace or reset the filesystem on restart or redeploy lose all stored data.
- **Redeploys:** `backend/appointments.json` and `backend/reminders.json` are tracked in Git, so a Git-based redeploy can reset them to the repository's version.
- **Shared conversation state:** an in-progress booking, cancellation or update is held in a single global file shared by every visitor, not per user or session - one visitor's "yes" can confirm another visitor's pending action.
- **No authentication:** every endpoint is public. `GET /webhook/appointments` and `GET /webhook/reminders` return all stored records to anyone.
- **Do not enter real patient or personal information.** Use made-up names and details only.

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

---

## 📄 API Contract (OpenAPI)

The HTTP API is documented as an OpenAPI 3.0 specification in [`docs/openapi.yaml`](docs/openapi.yaml). It covers every route the backend registers: `GET /`, `GET /health`, `POST /webhook/webhook`, `GET /webhook/appointments`, `GET /webhook/providers` and `GET /webhook/reminders`. For each one it gives the request body, the response envelope (messages, context stages and metadata) and the appointment, provider and reminder record shapes.

The spec describes the implementation **as it exists today**, including its quirks. For example, `POST /webhook/webhook` returns HTTP 200 even for errors (check the `success` field), and the list endpoints return bare JSON arrays. It is a static file, and no Swagger UI or other tooling is bundled. Open it in any OpenAPI viewer or editor.

**Authentication is not implemented.** Every endpoint is publicly callable by anyone who can reach the server.

---

## 🔒 Security & Production Readiness

Debug mode and CORS are both restricted by default (see Configuration above), but this project has no authentication, no rate limiting, and no HTTPS. It remains a prototype, not a production-hardened service.
