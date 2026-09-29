import logging
import os

from flask import Flask
from flask_cors import CORS
from backend import provider_repository
from backend.webhook import webhook_bp

# Metadata-only structured logging - see backend/LOGGING_NOTES.md for
# exactly what is and isn't logged. LOG_LEVEL defaults to INFO and is
# configurable through the environment; nothing here ever writes a log
# file, so this has no retention/rotation concerns of its own.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

# The only local frontend origin this project has ever actually used
# (frontend/package.json's "start" script is plain `react-scripts start`,
# which serves on port 3000) - not a guess, and not a production domain,
# since this project has never had one (see README.md's own "prototype,
# not production" framing). Used only as the fallback when
# CORS_ALLOWED_ORIGINS is unset, so local development keeps working
# unchanged with zero configuration.
DEFAULT_DEV_ORIGIN = "http://localhost:3000"

# Flask-Cors 4.0.0 treats any origin string containing one of these
# characters as a regex (flask_cors.core.probably_regex) and matches it
# with re.match - a prefix match. So "*" would allow every origin, and a
# typo like "https://app.example.com?" would also allow
# "https://app.example.co.evil.com". Literal origins never need them.
_REGEX_CHARS = frozenset('*\\?$^[]()')


def _parse_allowed_origins(raw_value):
    """Parses CORS_ALLOWED_ORIGINS into a list of origins for flask_cors.

    A comma-separated list, e.g. "http://localhost:3000,https://example.com" -
    each entry stripped, empty entries dropped. `raw_value` being None,
    blank, or resolving to no non-empty entries after parsing (e.g. ",,")
    all fall back to [DEFAULT_DEV_ORIGIN] identically - never silently
    resolving to "allow every origin" (flask_cors's own default) and never
    to "allow no origin", either of which a malformed value could
    otherwise produce silently.

    Raises ValueError if any entry contains a regex character (see
    _REGEX_CHARS) - failing loudly at startup rather than dropping the
    entry, so a misconfiguration is never silently accepted.
    """
    if not raw_value or not raw_value.strip():
        return [DEFAULT_DEV_ORIGIN]
    origins = [origin.strip() for origin in raw_value.split(',') if origin.strip()]
    for origin in origins:
        if _REGEX_CHARS.intersection(origin):
            raise ValueError(
                f"Invalid CORS_ALLOWED_ORIGINS entry {origin!r}: wildcards and "
                "regex characters are not allowed - list each exact origin, "
                "e.g. https://app.example.com"
            )
    return origins or [DEFAULT_DEV_ORIGIN]


def _parse_debug_flag(raw_value):
    """Parses FLASK_DEBUG into the `debug` argument passed to app.run() in
    the `python app.py` block below - only the exact value "true"
    (case-insensitive, whitespace-trimmed) enables it; None, blank, or any
    other value (e.g. "1", "yes") all resolve to False identically,
    matching backend/llm_config.LLM_ENABLED's own identical parsing
    convention. app.run()'s `debug` argument overrides Flask's own reading
    of the variable, so this rule governs the development server only.

    It does NOT govern the imported `app` (e.g. under Gunicorn, which never
    calls app.run()): Flask reads FLASK_DEBUG itself when the app is
    created, and treats any value other than unset/empty, "0", "false" or
    "no" (case-insensitive, NOT trimmed) as on - so "1", "yes" or "false "
    enable app.debug there. Keep FLASK_DEBUG unset or "false" anywhere the
    app is deployed.
    """
    return (raw_value or "").strip().lower() == "true"


# Read once, at process start - matching backend/llm_config.py's own
# "explicit env var, safe default, evaluated at import" convention (as
# opposed to backend/reminder_config.py's "read fresh every call"
# convention, which exists there specifically so a long-running process
# never needs restarting to pick up a changed CLINIC_TIMEZONE - neither
# reason applies here, since both of these are consulted exactly once,
# at the two startup calls below).
CORS_ALLOWED_ORIGINS = _parse_allowed_origins(os.environ.get("CORS_ALLOWED_ORIGINS"))
FLASK_DEBUG = _parse_debug_flag(os.environ.get("FLASK_DEBUG"))

# Create the Flask app
app = Flask(__name__)
# Largest request body accepted, in bytes. A normal chat turn is well under
# 1 KB; without a limit a single oversized request could exhaust the one
# Gunicorn worker's memory. Werkzeug raises RequestEntityTooLarge when a
# body exceeds this - see backend/webhook.py's handling of it.
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
# Restricted to CORS_ALLOWED_ORIGINS (default: the local frontend dev
# origin only) - previously CORS(app) allowed every origin
# unconditionally, which is unsafe for anything beyond local development.
CORS(app, origins=CORS_ALLOWED_ORIGINS)

# Register the webhook Blueprint at the '/webhook' endpoint
app.register_blueprint(webhook_bp, url_prefix='/webhook')

# Optional: root route just returns a simple message
@app.route('/')
def index():
    return {"message": "Healthcare Chatbot API is running."}


# Deployment health check. Loads and validates the provider reference data
# (providers.json / provider_availability.json) through provider_repository's
# own loaders - the one failure that leaves the process up while booking is
# broken. Read-only: it never touches appointments, reminders or pending
# files, never checks storage durability, and never calls the LLM. The
# ProviderDataError message holds absolute file paths, so only the
# exception type is logged and the response carries no details.
@app.route('/health')
def health():
    try:
        providers = provider_repository.load_providers()
        provider_repository.load_availability(providers=providers)
    except provider_repository.ProviderDataError as e:
        logger.warning("health check failed exception_type=%s", type(e).__name__)
        return {"status": "unavailable"}, 503
    return {"status": "ok"}

# Run the app
if __name__ == '__main__':
    # Debug mode is now OFF by default (previously hardcoded True, which
    # is unsafe for anything beyond local development - Flask's debug
    # mode enables the interactive debugger and code reloading, neither
    # of which should ever be reachable outside a developer's own
    # machine). Set FLASK_DEBUG=true to opt back into the previous local
    # development behavior. FLASK_DEBUG passed here overrides Flask's own,
    # looser reading of the variable - see _parse_debug_flag above.
    app.run(debug=FLASK_DEBUG)
