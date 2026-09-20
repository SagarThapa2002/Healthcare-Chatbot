"""A fake Claude provider for tests and local development - no network
access, no API key required, no real Anthropic call ever made.

Implements the exact same interface as claude_provider.generate_reply:
generate_reply(prompt, *, system=None) -> str. This lets assistant_service.py
(and anything downstream of it - routing, the safety policy, the response
contract, frontend rendering) be exercised end-to-end without a paid API
key. Selecting this provider is opt-in only (see llm_config.PROVIDER) and
never changes which safety/policy rules apply in assistant_service.py -
classify_request() runs before any provider, mock or real, is ever chosen.

This does NOT replace or weaken backend/claude_provider.py, which remains
the real Anthropic integration and is still the default provider.
"""

MOCK_REPLY = (
    "This is a mock assistant response for local development and testing. "
    "No real Claude API call was made."
)


def generate_reply(prompt, *, system=None):
    """Returns a fixed, clearly-labeled canned reply. Never makes a
    network call and never raises. `prompt` and `system` are accepted but
    ignored - only so this function's signature matches
    claude_provider.generate_reply exactly and either can be called the
    same way.
    """
    return MOCK_REPLY
