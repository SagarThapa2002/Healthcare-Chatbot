# LLM assistant — design notes and current status

## Current status: wired into the General FAQ path, disabled by default

`chatbot_logic.py` imports `assistant_service.py` (which itself imports
`claude_provider.py`). The General FAQ intent handler,
`_handle_general_faq()`, calls `assistant_service.answer()` whenever a
message is present - see that function's own docstring. `LLM_ENABLED`
still defaults to `false` (`backend/llm_config.py`), so being wired in
does not mean the assistant answers by default: an operator must
explicitly set `LLM_ENABLED=true`, and a real call to the Anthropic API
additionally requires a configured `ANTHROPIC_API_KEY` (`claude_provider.py`
raises `ProviderConfigError` otherwise). The deterministic `mock` provider
(`backend/mock_provider.py`, opt-in via `LLM_PROVIDER=mock`) remains
available for exercising this path in local development/tests without
either requirement. Every test in `backend/tests/test_claude_provider.py`
and `backend/tests/test_assistant_service.py` mocks the SDK client
entirely and passes without an `ANTHROPIC_API_KEY` set.

## Architecture

```
frontend (useConversation.js: General FAQ sends { message: text })
    v
chatbot_logic.py._handle_general_faq()   <- checks LLM_ENABLED + message present
    v
assistant_service.py        <- safety/policy boundary (this phase)
    v
claude_provider.py           <- thin Anthropic API adapter (Phase 5.4-A)
```

Claude is never the safety mechanism. Every safety-relevant decision -
whether to even consider asking Claude, and whether to trust what it said -
happens in `assistant_service.py`, deterministically, before or after the
one call `claude_provider.py` is allowed to make.

## Policy categories implemented (`assistant_service.classify_request`)

Deterministic, word-boundary regex matching over the **phrasing** of the
request - not medical knowledge. This module does not know what any
disease or medication actually is, and does not need to, in order to
recognize the *shape* of a request it must refuse.

| Category | Triggered by phrasing like | Reaches Claude? |
|---|---|---|
| `appointment_action` | "book", "cancel", "reschedule", or "appointment" | Never |
| `diagnosis_request` | "do I have", "diagnose", "what disease/condition..." | Never |
| `medication_request` | "should I take/stop taking", "change my dose" | Never |
| `treatment_request` | "what treatment should I", "how should I treat my" | Never |
| `clinician_replacement` | "be my doctor", "act as my physician" | Never |
| `empty_input` | empty or whitespace-only message | Never |
| `llm_disabled` | any otherwise-allowed message, while `LLM_ENABLED=false` | Never |

Only a message that matches none of the above, **and** `LLM_ENABLED=true`,
ever reaches `claude_provider.generate_reply()`.

## What is NOT handled here, and why

- **Symptom/emergency urgency detection.** That is `backend/symptom_triage.py`,
  and it stays entirely separate. This module makes no attempt to detect
  emergencies itself - it assumes a future router checks symptom triage
  *first* and skips this module entirely for emergency/urgent cases, so
  the deterministic triage decision can never be second-guessed or
  overridden by an LLM call that never happens. Duplicating any part of
  that logic here was deliberately avoided (see the healthcare constraint
  below).
- **"Claims certainty when information is insufficient."** This isn't
  something a deterministic input scan can judge without medical
  knowledge, so it isn't attempted as an input-classification category.
  It's addressed two other ways: the system prompt explicitly instructs
  against it, and the output-safety scan below flags a few certainty-
  claiming phrase patterns after the fact. Neither is a guarantee.

## Output-safety scan — read this before assuming it does more than it does

`assistant_service._passes_output_safety_check()` is a **coarse,
non-exhaustive, keyword/pattern scan** applied to whatever Claude actually
returned. It is defense-in-depth only. A response passing this check is
**not** "verified safe" - it only means it didn't match one of a handful
of obviously problematic patterns (e.g. "you definitely have...", "I
diagnose you..."). This fact is enforced as a real, tested constant
(`OUTPUT_SAFETY_CHECK_DISCLAIMER`) specifically so it can't quietly be
described as more than it is in a later phase. **Do not extend this into
a claim of clinical validation, and do not treat it as a substitute for
the system prompt.**

## Never exposed

API keys, environment variable names/values, the system prompt itself,
and internal exception details are never included in any text returned to
a caller. Every provider failure (`claude_provider.ProviderError`) and any
other unexpected exception is converted to the same generic, calm
fallback message - never `str(exception)`, never a traceback. The system
prompt also explicitly instructs Claude never to reveal itself, its
configuration, or its instructions, regardless of how it's asked (a
prompt-level instruction, not a technical guarantee - see Risks).

## Healthcare constraint honored in this phase

No clinical rules, diagnoses, emergency thresholds, medications, clinical
statistics, citations, or medical advice were invented anywhere in this
module, its tests, or this document. The policy patterns above match
*request phrasing* ("do I have", "should I take"), not medical content.
The system prompt is a scope/boundary statement, not clinical guidance.

## What still needs human review before real use

- The exact wording of the system prompt and refusal messages (currently
  reasonable first drafts, not clinically or legally reviewed).
- The policy phrase list and output-safety pattern list are illustrative
  and non-exhaustive - false negatives (a request that should be refused
  but isn't recognized) are expected and should be found through real
  testing, not assumed away.
- ~~The exact wiring point in `chatbot_logic.py` and how
  `assistant_service.answer()`'s result maps onto a `response_model.py`
  message type~~ - resolved: wired at `_handle_general_faq()`, which maps
  an allowed LLM response onto `response_model.assistant_response_message()`
  and every other outcome (refused/disabled/failed) onto the existing
  `response_model.text_message()` (see that function's own docstring).
- Whether/how a future router should also pass conversation-level context
  (e.g. "the user is mid-symptom-check") into the policy decision - out of
  scope here; this phase only ever sees one plain message at a time.
