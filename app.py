import logging
import os

from flask import Flask
from flask_cors import CORS
from backend.webhook import webhook_bp

# Metadata-only structured logging - see backend/LOGGING_NOTES.md for
# exactly what is and isn't logged. LOG_LEVEL defaults to INFO and is
# configurable through the environment; nothing here ever writes a log
# file, so this has no retention/rotation concerns of its own.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

# The only local frontend origin this project has ever actually used
# (frontend/package.json's "start" script is plain `react-scripts start`,
# which serves on port 3000) - not a guess, and not a production domain,
# since this project has never had one (see README.md's own "prototype,
# not production" framing). Used only as the fallback when
# CORS_ALLOWED_ORIGINS is unset, so local development keeps working
# unchanged with zero configuration.
DEFAULT_DEV_ORIGIN = "http://localhost:3000"


def _parse_allowed_origins(raw_value):
    """Parses CORS_ALLOWED_ORIGINS into a list of origins for flask_cors.

    A comma-separated list, e.g. "http://localhost:3000,https://example.com" -
    each entry stripped, empty entries dropped. `raw_value` being None,
    blank, or resolving to no non-empty entries after parsing (e.g. ",,")
    all fall back to [DEFAULT_DEV_ORIGIN] identically - never silently
    resolving to "allow every origin" (flask_cors's own default) and never
    to "allow no origin", either of which a malformed value could
    otherwise produce silently.
    """
    if not raw_value or not raw_value.strip():
        return [DEFAULT_DEV_ORIGIN]
    origins = [origin.strip() for origin in raw_value.split(',') if origin.strip()]
    return origins or [DEFAULT_DEV_ORIGIN]


def _parse_debug_flag(raw_value):
    """Parses FLASK_DEBUG into a bool - only the exact value "true"
    (case-insensitive, whitespace-trimmed) enables it; None, blank, or any
    other value (e.g. "1", "yes") all resolve to False identically,
    matching backend/llm_config.LLM_ENABLED's own identical parsing
    convention. Fails safe toward OFF - a malformed value can never
    accidentally enable debug mode.
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

# Run the app
if __name__ == '__main__':
    # Debug mode is now OFF by default (previously hardcoded True, which
    # is unsafe for anything beyond local development - Flask's debug
    # mode enables the interactive debugger and code reloading, neither
    # of which should ever be reachable outside a developer's own
    # machine). Set FLASK_DEBUG=true to opt back into the previous local
    # development behavior.
    app.run(debug=FLASK_DEBUG)
