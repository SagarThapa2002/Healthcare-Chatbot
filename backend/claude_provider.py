"""Thin adapter for the Anthropic Messages API - the SDK foundation only.

Scope (Phase 5.4-A): this module knows how to send one stateless prompt to
Claude and return plain text, or raise a typed error. It knows NOTHING
about healthcare policy, safety guardrails, conversation routing, or
conversation history - that belongs in a later, separate module
(assistant_service.py) that would call this one.

Reached from the live chatbot via assistant_service.py (called from
chatbot_logic.py's _handle_general_faq(), see
backend/LLM_ASSISTANT_NOTES.md) - webhook.py itself still does not import
this module directly. Importing this module never makes a network call -
the Anthropic client is only constructed, and the API is only called,
inside generate_reply(), and only when assistant_service._get_provider()
selects this module (the default) after LLM_ENABLED and the policy check
both pass.

Verified against the actually-installed anthropic==1.7.0 package via
direct introspection (constructor signatures, exception hierarchy, default
timeout/retry values) rather than assumed from documentation alone.
"""
import anthropic

from backend import llm_config


class ProviderError(Exception):
    """Base class for every error this module raises.

    Callers should catch this (or a specific subclass below) rather than
    letting a raw anthropic SDK exception escape - a later, separate phase
    (assistant_service.py) is what turns this into a safe, calm fallback
    message instead of a crash. Nothing does that yet.
    """


class ProviderConfigError(ProviderError):
    """Raised when the provider cannot be used due to missing/invalid
    configuration (e.g. no API key set) - not an Anthropic API error."""


class ProviderTimeoutError(ProviderError):
    """Raised when the request to Anthropic timed out."""


class ProviderAPIError(ProviderError):
    """Raised when Anthropic's API itself returned an error - auth
    failure, rate limit, bad request, server error, connection failure,
    etc. Wraps anthropic.APIError and its subclasses generically; this
    module does not need to distinguish between them further."""


class ProviderResponseError(ProviderError):
    """Raised when Anthropic returned a response but it contained no
    usable text content (empty, blank, or non-text-only content blocks)."""


def generate_reply(prompt, *, system=None):
    """Sends a single, stateless prompt to Claude and returns the plain
    text reply.

    No conversation history: each call is independent - only `prompt`
    (and optionally `system`) is sent. No automatic retries: the client is
    constructed with max_retries=0, overriding the SDK's own default of 2.
    An explicit timeout (backend.llm_config.TIMEOUT_SECONDS) is always
    set, overriding the SDK's own 10-minute default.

    Raises a ProviderError subclass on any failure - a missing API key, a
    timeout, an API-level error, or a malformed/empty response. Never lets
    a raw anthropic exception or raw/unvalidated model output propagate to
    the caller.
    """
    if not llm_config.has_api_key():
        raise ProviderConfigError("ANTHROPIC_API_KEY is not configured")

    client = anthropic.Anthropic(
        api_key=llm_config.get_api_key(),
        timeout=llm_config.TIMEOUT_SECONDS,
        max_retries=0,
    )

    create_kwargs = {
        "model": llm_config.MODEL,
        "max_tokens": llm_config.MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        create_kwargs["system"] = system

    try:
        response = client.messages.create(**create_kwargs)
    except anthropic.APITimeoutError as e:
        # Must be caught before the broader APIError below - APITimeoutError
        # is itself a subclass of APIError (confirmed via introspection).
        raise ProviderTimeoutError(str(e)) from e
    except anthropic.APIError as e:
        raise ProviderAPIError(str(e)) from e

    text = _extract_text(response)
    if not text:
        raise ProviderResponseError("Claude returned no usable text content")
    return text


def _extract_text(response):
    """Joins every text content block into a single string. Anthropic
    responses can contain non-text blocks (e.g. tool_use) - none are used
    here since no tools are configured, but this stays defensive rather
    than assuming content[0] is always a text block."""
    content = getattr(response, "content", None) or []
    parts = [
        block.text
        for block in content
        if getattr(block, "type", None) == "text" and getattr(block, "text", None)
    ]
    return "".join(parts).strip()
