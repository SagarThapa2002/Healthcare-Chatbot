# Dialogflow ES scaffold

## What this is

This is a **hand-authored, minimal Dialogflow ES agent scaffold**. It was
written by reading the intent names and parameters that
`backend/chatbot_logic.py` already dispatches on, and describing them in a
Dialogflow-ES-shaped JSON format.

## What this is NOT

- **This is not an export from a live Dialogflow agent.** No Dialogflow
  agent currently exists for this project (verified: no agent files were
  ever committed to this repository's history, and no Dialogflow SDK is a
  dependency anywhere in `backend/requirements.txt`).
- **The training phrases have not been validated in Dialogflow.** They are
  plausible example utterances inferred from the existing keyword/regex
  matching in `frontend/src/conversation/intent.js`, not phrases that have
  been tested against a real NLU model. Importing this scaffold into
  Dialogflow is not guaranteed to reproduce the current app's behavior.
- **This is not a complete production export.** Real Dialogflow ES exports
  include additional fields this scaffold omits for readability - annotated
  training-phrase parts, per-intent response messages, contexts, events,
  fallback-intent flags, and an agent-level `package.json`. Adapting this
  scaffold into a real, importable agent would require filling those in.

## Why it exists

To give the existing intent/parameter contract - today defined only as
scattered `if`/`elif` string comparisons in `chatbot_logic.py` and a keyword
matcher in the frontend - a single, version-controlled, human-readable
description. It is a starting point for eventually building a real
Dialogflow agent, not a working one.

## Current runtime reality (important)

Dialogflow is **not** in the runtime loop today, and importing this
scaffold does not change that. The actual flow is:

```
React frontend (conversation/intent.js: keyword/regex matching)
  -> constructs a Dialogflow-fulfillment-shaped request itself
  -> POSTs directly to the Flask backend (api/client.js)
  -> backend/webhook.py -> backend/chatbot_logic.py
```

The backend's webhook request/response shape mirrors what a real Dialogflow
ES fulfillment webhook would send and expect, but no Dialogflow agent is
actually calling it - the frontend calls it directly and does its own
intent classification client-side.

## Intents and parameters

Each file in `intents/` is named exactly after the intent `displayName`
string `backend/chatbot_logic.py` already compares against, so the two can
be cross-checked directly.

| Intent | Parameters | Backend handler |
|---|---|---|
| `Symptom Check` | `symptom` | `_handle_symptom_check` |
| `Book Appointment` | `name`, `date`, `time` | `_handle_book_appointment` |
| `YesIntent` | *(none)* | `_handle_yes_intent` |
| `NoIntent` | *(none)* | `_handle_no_intent` |
| `Update Appointment` | `name`, `date`, `time` | `_handle_update_appointment` |
| `Cancel Appointment` | `name` | `_handle_cancel_appointment` |
| `View Appointments` | *(none)* | `_handle_view_appointments` |
| `General FAQ` | *(none)* | `_handle_general_faq` |

No parameter is marked `required`. The current code does not perform
Dialogflow-style required-parameter prompting: `Book Appointment`'s
name/date/time are validated client-side, step by step, in
`frontend/src/conversation/validation.js` and `dateTime.js`; `Cancel
Appointment` and `Update Appointment` read `name` without any validation at
all in `chatbot_logic.py`. Marking parameters `required` here would
describe behavior the app doesn't actually have.

No contexts are defined. The multi-turn booking flow (collect name, then
date, then time, then confirm) is state managed entirely by the React
frontend (`frontend/src/conversation/booking.js`), not by Dialogflow
contexts - each webhook call today is independent. A real Dialogflow agent
built from this scaffold would need its own decision about whether to keep
that orchestration in the frontend (as now) or move it into Dialogflow
contexts.

No custom entities are defined. Parameters use Dialogflow's built-in system
entities (`@sys.person`, `@sys.date`, `@sys.time`) or `@sys.any` for
`symptom`, since the app does not constrain symptom text to any fixed list.

## Scope note

The `symptom` training phrases above are plain example user utterances
chosen only to match the existing keyword list in `SYMPTOM_PATTERN`
(`frontend/src/conversation/intent.js`). They are not medical guidance and
were not chosen to represent any particular clinical category.
