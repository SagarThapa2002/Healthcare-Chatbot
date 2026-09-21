"""Structured response envelope for the /webhook/webhook API.

This is the single place that knows the shape of the response contract
(schemaVersion "1.0"). chatbot_logic.py builds `messages` using the
builder functions here and hands them to success_response/error_response
to get the full envelope - nothing else should construct these dicts by
hand, so the shape stays consistent and centrally testable.
"""
import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"


def _new_request_id():
    return str(uuid.uuid4())


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def new_request_id():
    """Public entry point for generating a request id outside this module.

    Lets webhook.py generate exactly one id per request up front and thread
    it through logging and into the eventual response meta, instead of a
    second, uncorrelated id being generated here later.
    """
    return _new_request_id()


def _build_meta(request_id=None):
    return {
        "schemaVersion": SCHEMA_VERSION,
        "requestId": request_id or _new_request_id(),
        "timestamp": _now_iso(),
    }


def text_message(text, suggestions=None):
    return {
        "type": "text",
        "content": {"text": text},
        "suggestions": suggestions or [],
    }


def validation_error_message(text, suggestions=None):
    """Not currently emitted by any webhook branch.

    All input validation today (name/date/time format) happens client-side
    in the frontend's conversation/*.js before the backend is ever called,
    so the backend has no genuine occasion to use this yet. It is
    implemented and tested here so the message type is real and ready for
    when the backend gains server-side validation of its own.
    """
    return {
        "type": "validation_error",
        "content": {"text": text},
        "suggestions": suggestions or [],
    }


def booking_confirmation_message(text, appointment, suggestions=None):
    """Only use this where a real, persisted appointment record exists.

    Do not use this for the "please confirm - yes or no?" prompt: nothing
    is booked yet at that point, so that prompt stays a plain text_message.
    """
    return {
        "type": "booking_confirmation",
        "content": {"text": text, "appointment": appointment},
        "suggestions": suggestions or [],
    }


def symptom_guidance_message(text, urgency, matched_rules, suggestions=None):
    """Not currently emitted by any webhook branch - see backend/symptom_triage.py
    and backend/SYMPTOM_RULES_SOURCES.md. This is an additive builder only:
    chatbot_logic.py does not call symptom_triage.classify_symptom() yet, so
    nothing in the live app produces this message type today. Wiring it in
    (and teaching the frontend to render it) is a deliberate, separate,
    later step - see the Phase 5.3 design notes for why.

    `urgency` and `matchedRules` ride alongside `text` in `content`, the
    same way booking_confirmation_message carries `appointment` alongside
    its own `text`.
    """
    return {
        "type": "symptom_guidance",
        "content": {"text": text, "urgency": urgency, "matchedRules": list(matched_rules)},
        "suggestions": suggestions or [],
    }


def assistant_response_message(text, *, provider="claude", suggestions=None):
    """Only for a genuine successful response from the LLM assistant
    (backend/assistant_service.py). Deterministic responses (appointments,
    symptom guidance, general FAQ fallback text, etc.) must never use this
    builder or carry this metadata - `provider` identifies Claude only
    when Claude actually produced the text.
    """
    return {
        "type": "assistant_response",
        "content": {
            "text": text,
            "provider": provider,
            "disclaimer": "AI-generated general information, not medical advice.",
        },
        "suggestions": suggestions or [],
    }


def success_response(
    messages, intent, request_id=None, booking_stage=None, cancellation_stage=None, update_stage=None,
):
    """`booking_stage`/`cancellation_stage`/`update_stage`, if given, are
    folded into `context` alongside `intent` - all optional and additive,
    so every existing caller that doesn't pass them gets the exact same
    `context` shape as before.

    Phase 6.1, Slice 3, Step 4 (revised): `booking_stage` lets a caller
    (chatbot_logic.py's Book Appointment / YesIntent handling) structurally
    report which stage of the booking flow it is now waiting on - one of
    "name", "provider", "date", "slot", "confirm", "booked" - so the
    frontend can use it as the authority for whether a just-submitted
    provider/slot value was actually accepted, instead of inferring that
    from response text or `success` (which only means the request was
    processed, not that any particular field was valid).

    `cancellation_stage` is the same idea for the cancel-by-ID flow,
    folded into `context` as `cancellationStage` - one of "identifier",
    "confirm", "cancelled".

    Phase 6.1 Slice B: `update_stage` is the same idea again for the
    update-by-ID flow, folded into `context` as `updateStage` - one of
    "identifier", "fields", "confirm", "updated". All three stage fields
    are deliberately separate, never reused between flows, so a client
    can always tell which (if any) flow a response belongs to.
    """
    context = {"intent": intent}
    if booking_stage is not None:
        context["bookingStage"] = booking_stage
    if cancellation_stage is not None:
        context["cancellationStage"] = cancellation_stage
    if update_stage is not None:
        context["updateStage"] = update_stage
    return {
        "success": True,
        "error": None,
        "messages": messages,
        "context": context,
        "meta": _build_meta(request_id=request_id),
    }


def error_response(message, code="INTERNAL_ERROR", request_id=None):
    return {
        "success": False,
        "error": {"code": code, "message": message},
        "messages": [],
        "context": None,
        "meta": _build_meta(request_id=request_id),
    }
