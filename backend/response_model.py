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


def _build_meta():
    return {
        "schemaVersion": SCHEMA_VERSION,
        "requestId": _new_request_id(),
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


def success_response(messages, intent):
    return {
        "success": True,
        "error": None,
        "messages": messages,
        "context": {"intent": intent},
        "meta": _build_meta(),
    }


def error_response(message, code="INTERNAL_ERROR"):
    return {
        "success": False,
        "error": {"code": code, "message": message},
        "messages": [],
        "context": None,
        "meta": _build_meta(),
    }
