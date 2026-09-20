"""Configuration for the (not-yet-wired-in) LLM assistant feature.

Everything here is read from environment variables with explicit, safe
defaults. Nothing in this module makes a network call, and nothing in the
live chatbot dispatch (chatbot_logic.py / webhook.py) imports it yet - see
backend/claude_provider.py's module docstring for the current scope.
"""
import os

# Master switch, off by default. Installing the anthropic SDK and adding
# this module has zero effect on current behavior until a later, separate
# phase both wires it into chatbot_logic.py AND someone opts in here.
LLM_ENABLED = os.environ.get("LLM_ENABLED", "false").strip().lower() == "true"

# No "latest" - an explicit, reviewable default that only changes when a
# human updates it, matching the same convention already used for
# response_model.SCHEMA_VERSION and symptom_triage.SCHEMA_VERSION. Sourced
# from Anthropic's own current official documentation examples
# (platform.claude.com/docs/en/cli-sdks-libraries/sdks/python) as of
# 2026-09-20 - re-verify against current docs if this is ever revisited.
DEFAULT_MODEL = "claude-opus-5"
MODEL = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

# Which provider assistant_service.py should call. "claude" (default) is
# the real Anthropic integration in backend/claude_provider.py. "mock" is
# an opt-in, no-network provider (backend/mock_provider.py) for tests and
# local development without a paid API key. Any other/unset value falls
# back to "claude" - unrecognized configuration fails safe toward the real
# integration, never toward the mock.
PROVIDER = os.environ.get("LLM_PROVIDER", "claude").strip().lower()

DEFAULT_MAX_TOKENS = 512
MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", DEFAULT_MAX_TOKENS))

# The SDK's own default timeout is 10 minutes (anthropic's internal
# DEFAULT_TIMEOUT), which is far too long for a synchronous Flask request.
# This gives claude_provider.py an explicit, short default instead.
DEFAULT_TIMEOUT_SECONDS = 30.0
TIMEOUT_SECONDS = float(os.environ.get("ANTHROPIC_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))


def get_api_key():
    """Returns the configured API key, or None if unset.

    Never hard-code a key here or anywhere else - this only reads from the
    environment. Callers decide how to react to a missing key (see
    claude_provider.ProviderConfigError).
    """
    return os.environ.get("ANTHROPIC_API_KEY") or None


def has_api_key():
    return get_api_key() is not None
