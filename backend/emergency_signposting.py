"""Deterministic emergency signposting for free-text chat messages.

A deliberately small set of explicit red-flag phrases, taken from NHS and
Samaritans guidance (see backend/SYMPTOM_RULES_SOURCES.md), each mapped to a
fixed reply that points the user to 999, NHS 111 or Samaritans. It does not
diagnose, assess urgency, or recognise every emergency: no match never means
a situation is safe. It never calls an LLM. UK services only.

chatbot_logic._dispatch_webhook_request runs signpost() on the free text of
a Symptom Check or General FAQ request before either handler - and so before
any LLM call. Nothing here logs or returns the user's text.
"""
import re

PHYSICAL_EMERGENCY = "physical_emergency"
POISONING = "poisoning"
CRISIS = "crisis"

_PRONOUN = r"(?:my|his|her|their|the)"

# Each category's phrases, matched against normalized text (see _normalize)
# with word boundaries, so a word merely containing a phrase never matches.
_PATTERNS = {
    # NHS heart attack and shortness of breath pages: chest pain that feels
    # tight, heavy or squeezing, or spreads to the arms, neck or jaw; severe
    # difficulty breathing (gasping, choking, can't get words out); blue or
    # grey lips or skin. NHS poisoning page: unconscious, not breathing.
    PHYSICAL_EMERGENCY: [
        rf"\b(?:crushing|squeezing|tight|heavy|severe)\s+(?:chest\s+pain|pain\s+in\s+{_PRONOUN}\s+chest)\b",
        r"\bchest\s+(?:feels?|is|felt)\s+(?:really\s+|very\s+)?(?:tight|heavy)\b",
        r"\btight\s+chest\b",
        r"\bchest\s+pain\b.{0,80}\b(?:arm|arms|neck|jaw)\b",
        r"\b(?:can\s*not|can't|cant|unable\s+to|struggling\s+to)\s+breathe\b",
        r"\b(?:severe|serious)\s+difficulty\s+breathing\b",
        r"\bgasping\s+for\s+(?:breath|air)\b",
        r"\bchoking\b",
        r"\b(?:not|stopped)\s+breathing\b",
        r"\b(?:lips|skin|face)\b.{0,25}\b(?:blue|grey|gray)\b",
        r"\b(?:unconscious|unresponsive)\b",
    ],
    # NHS poisoning page; NHS urgent mental health help page (overdose).
    POISONING: [
        r"\b(?:swallowed|drank|drunk|ingested|ate|eaten)\b.{0,40}"
        r"\b(?:bleach|poison|weed\s*killer|antifreeze|detergent|button\s+batter(?:y|ies)"
        r"|cleaning\s+(?:product|fluid|liquid))\b",
        r"\b(?:overdose|overdosed)\b",
        r"\b(?:took|taken|swallowed)\s+too\s+many\s+(?:pills|tablets|painkillers)\b",
    ],
    # NHS urgent mental health help page; Samaritans. Explicit statements of
    # suicidal intent or self-harm only - not general low mood.
    CRISIS: [
        r"\bkill\s+myself\b",
        r"\b(?:end|ending|take|taking)\s+my\s+(?:own\s+)?life\b",
        r"\bcommit\s+suicide\b",
        r"\bsuicidal\b",
        r"\bwant\s+to\s+die\b",
        r"\b(?:don'?t|do\s+not)\s+want\s+to\s+(?:live|be\s+alive)\b",
        r"\b(?:hurt|harm|cut)\s+myself\b",
        r"\bself\s?harm(?:ing|ed)?\b",
    ],
}

_COMPILED = {category: [re.compile(p) for p in patterns] for category, patterns in _PATTERNS.items()}

# Checked in this order; the first matching category gives the main reply.
_ORDER = (PHYSICAL_EMERGENCY, POISONING, CRISIS)

NOT_AN_EMERGENCY_SERVICE = "I'm a chatbot, not an emergency service, and I can't contact anyone for you."

_REPLIES = {
    PHYSICAL_EMERGENCY: (
        "This could be a medical emergency. Please call 999 now. "
        f"{NOT_AN_EMERGENCY_SERVICE} "
        "If you're not sure it's an emergency but need medical help right now, call NHS 111. "
        "(UK numbers.)"
    ),
    POISONING: (
        "If someone may have swallowed something harmful or taken an overdose, get help now. "
        "Call 999 if they are unconscious, not breathing, having severe difficulty breathing "
        "or having a seizure. Otherwise call NHS 111 straight away. Do not try to make them sick "
        "or give them anything to eat or drink. "
        f"{NOT_AN_EMERGENCY_SERVICE} (UK numbers.)"
    ),
    CRISIS: (
        "I'm really sorry you're feeling like this. You don't have to deal with it alone. "
        "If you have hurt yourself, might act on these thoughts, or can't keep yourself safe, "
        "call 999 now. You can talk to Samaritans for free, any time, day or night, on 116 123. "
        "For urgent mental health help, call NHS 111 and choose the mental health option. "
        f"{NOT_AN_EMERGENCY_SERVICE} (UK numbers.)"
    ),
}

# Added when crisis wording appears alongside a physical or poisoning red flag.
_CRISIS_SUPPORT = "You can also talk to Samaritans for free, any time, day or night, on 116 123."


def _normalize(text):
    """Lowercase, straight apostrophes, other punctuation (including hyphens)
    to spaces, single spaces - so "Chest-pain!!" and "chest pain" read alike.
    """
    text = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"[^a-z0-9'\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def match_categories(text):
    """The red-flag categories `text` matches, in _ORDER; [] for none or for
    anything that is not a string.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    normalized = _normalize(text)
    return [c for c in _ORDER if any(p.search(normalized) for p in _COMPILED[c])]


def signpost(text):
    """The fixed signposting reply for `text`, or None if no red flag matches."""
    categories = match_categories(text)
    if not categories:
        return None
    reply = _REPLIES[categories[0]]
    if categories[0] != CRISIS and CRISIS in categories:
        reply = f"{reply} {_CRISIS_SUPPORT}"
    return reply
