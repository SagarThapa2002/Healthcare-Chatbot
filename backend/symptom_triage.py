"""Deterministic, rule-based, non-diagnostic symptom triage.

This module is intentionally separate from chatbot_logic.py (appointment/
booking logic) and is NOT wired into the live webhook dispatch yet. It is a
standalone, fully tested capability - see the Phase 5.3 design notes and
backend/SYMPTOM_RULES_SOURCES.md for why wiring it in is a deliberate,
separate, later step.

What this module WILL do:
  - Match user-provided symptom text against a fixed, versioned, JSON-defined
    set of keyword rules, using word-boundary matching only (never
    unanchored substring matching).
  - Classify the result into one of a small set of urgency categories,
    based purely on which rule(s) matched.
  - Return pre-written, non-diagnostic guidance text associated with the
    matched category.
  - Do all of this deterministically and locally: the same input and rule
    set always produce the same output.

What this module WILL NOT do:
  - Diagnose a disease or name a specific medical condition.
  - Produce a probability or any statistical estimate of a diagnosis.
  - Ask follow-up questions designed to narrow down a diagnosis.
  - Call an LLM, an ML model, or any external service - this is 100%
    static, local, rule-based logic.

Urgency vocabulary (see URGENCY_LEVELS / UNKNOWN_URGENCY below):
  emergency - a matched rule indicates a symptom that can be a sign of a
              life-threatening or rapidly serious problem. Guidance directs
              the user to seek emergency care immediately.
  urgent    - warrants prompt medical attention, not immediately
              life-threatening.
  routine   - common, usually self-limiting; general self-care guidance,
              see a provider if it worsens or persists.
  general   - LOW-SPECIFICITY wellness guidance (e.g. general tiredness).
              This is NOT a clinical severity classification - it exists
              for vague, non-specific mentions that don't indicate a
              particular medical concern.
  unknown   - NOT a clinical tier. Means no rule matched at all. Must never
              be silently treated as "general" or "routine" - see
              classify_symptom() below.

Production backend/symptom_rules.json currently contains ZERO active rules:
no rule content has been clinically reviewed or sourced yet. Until real,
sourced rules are added, classify_symptom() will resolve every input to
"unknown" against the production file. See SYMPTOM_RULES_SOURCES.md.
"""
import json
import os
import re

RULES_FILE = os.path.join(os.path.dirname(__file__), 'symptom_rules.json')

SCHEMA_VERSION = "1.0"

# Rule-level urgency values. "unknown" is deliberately excluded here - it is
# reserved for "no rule matched" and can never be assigned to a rule.
URGENCY_LEVELS = ("emergency", "urgent", "routine", "general")
UNKNOWN_URGENCY = "unknown"

# Severity rank used ONLY to resolve which matched rule's message wins when
# more than one rule matches. This is a fixed property of the tier name,
# never data read from the rules file, so a mis-set `priority` in the JSON
# can never make a lower urgency tier outrank a higher one.
_URGENCY_RANK = {
    "emergency": 3,
    "urgent": 2,
    "routine": 1,
    "general": 0,
}

# Escalation is DERIVED from urgency via this one fixed mapping. It is
# never stored per-rule in the JSON, so urgency and escalation can never
# drift out of sync with each other.
_ESCALATION_BY_URGENCY = {
    "emergency": "emergency_services",
    "urgent": "book_appointment_soon",
    "routine": "self_care",
    "general": "self_care",
    UNKNOWN_URGENCY: "none",
}

_UNKNOWN_MESSAGE = (
    "I don't have specific guidance for that symptom. If you're concerned, "
    "please consider speaking with a healthcare provider. If you think you "
    "may have a medical emergency, contact emergency services."
)

_REQUIRED_RULE_FIELDS = ("id", "keywords", "urgency", "message", "priority", "reference")


class SymptomRuleError(ValueError):
    """Raised when symptom_rules.json is missing, malformed, or invalid.

    Deliberately fails loudly rather than silently dropping a bad rule or
    continuing with a partial rule set - for a safety-relevant feature, a
    loud startup/load failure is far preferable to silently-wrong data.
    """


def _validate_rule(rule, index):
    if not isinstance(rule, dict):
        raise SymptomRuleError(f"rules[{index}] must be an object, got {type(rule).__name__}")

    for field in _REQUIRED_RULE_FIELDS:
        if field not in rule:
            raise SymptomRuleError(
                f"rules[{index}] ({rule.get('id', '?')!r}) is missing required field {field!r}"
            )

    rule_id = rule["id"]
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise SymptomRuleError(f"rules[{index}] has an invalid 'id' - must be a non-empty string")

    keywords = rule["keywords"]
    if not isinstance(keywords, list) or not keywords:
        raise SymptomRuleError(f"rule {rule_id!r} has an invalid 'keywords' - must be a non-empty list")
    for keyword in keywords:
        if not isinstance(keyword, str) or not keyword.strip():
            raise SymptomRuleError(
                f"rule {rule_id!r} has an invalid keyword entry {keyword!r} - must be a non-empty string"
            )

    if rule["urgency"] not in URGENCY_LEVELS:
        raise SymptomRuleError(
            f"rule {rule_id!r} has an invalid urgency {rule['urgency']!r} - must be one of "
            f"{URGENCY_LEVELS} ('unknown' is reserved for 'no rule matched' and cannot be "
            "assigned to a rule)"
        )

    if not isinstance(rule["message"], str) or not rule["message"].strip():
        raise SymptomRuleError(f"rule {rule_id!r} has an invalid 'message' - must be a non-empty string")

    priority = rule["priority"]
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise SymptomRuleError(f"rule {rule_id!r} has an invalid 'priority' - must be an integer")

    if not isinstance(rule["reference"], str) or not rule["reference"].strip():
        raise SymptomRuleError(f"rule {rule_id!r} has an invalid 'reference' - must be a non-empty string")


def load_rules(path=None):
    """Loads and strictly validates a symptom rules file.

    Raises SymptomRuleError on anything malformed - a missing file, invalid
    JSON, an unsupported schemaVersion, a non-list 'rules', a rule missing a
    required field, an invalid field type/value, or a duplicate rule id.
    Never silently skips a bad rule or returns a partial rule set.
    """
    file_path = path or RULES_FILE

    if not os.path.exists(file_path):
        raise SymptomRuleError(f"symptom rules file not found: {file_path}")

    with open(file_path, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise SymptomRuleError(f"symptom rules file is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise SymptomRuleError("symptom rules file must contain a JSON object")

    if data.get("schemaVersion") != SCHEMA_VERSION:
        raise SymptomRuleError(
            f"unsupported symptom rules schemaVersion: {data.get('schemaVersion')!r} "
            f"(expected {SCHEMA_VERSION!r})"
        )

    rules = data.get("rules")
    if not isinstance(rules, list):
        raise SymptomRuleError("symptom rules file must have a 'rules' array")

    seen_ids = set()
    for index, rule in enumerate(rules):
        _validate_rule(rule, index)
        if rule["id"] in seen_ids:
            raise SymptomRuleError(f"duplicate rule id: {rule['id']!r}")
        seen_ids.add(rule["id"])

    return rules


def _normalize(text):
    return ' '.join((text or '').strip().lower().split())


def _keyword_pattern(keyword):
    # re.escape guards against a keyword containing regex-special characters
    # (e.g. a stray "(" or "?" in hand-authored data) being interpreted as
    # regex syntax instead of literal text.
    #
    # Boundaries use negative lookaround, not \b. \b only fires at a
    # transition between a \w character and a non-\w character, so a
    # keyword that itself starts or ends with punctuation (e.g.
    # "pain (mild)") could never satisfy a trailing \b when followed by
    # another non-\w character such as a space: both sides of that
    # position are already non-\w, so \b cannot match there at all, and
    # the keyword would silently fail to match even when literally
    # present in the text (discovered during Phase 5.3 verification).
    # Lookaround instead asks the more direct question - "is the
    # character immediately outside the match a \w character?" - which
    # gives the right answer regardless of what the keyword's own edge
    # characters are. It is exactly equivalent to \b's own word-character
    # definition, so every keyword that itself starts/ends with a \w
    # character (i.e. every keyword in use today) matches identically to
    # before; only punctuation-edged keywords behave differently, and
    # only in that they now correctly match. Never unanchored substring
    # matching either way.
    escaped = re.escape(keyword.strip().lower())
    return re.compile(r'(?<!\w)' + escaped + r'(?!\w)')


def classify_symptom(text, rules=None):
    """Matches `text` against `rules` (or the production rules file, loaded
    fresh, if not given) and returns:

        {
            "urgency": "emergency" | "urgent" | "routine" | "general" | "unknown",
            "matchedRules": [rule_id, ...],  # every matched rule, winner first
            "message": "...",                 # the winning rule's message, or
                                                # the unknown-case fallback
            "escalation": "...",               # derived from urgency, never
                                                # stored per-rule
        }

    Deterministic: identical text and rules always produce an identical
    result. Evaluates every rule (not first-match-wins), so more than one
    symptom in a single message is fully recorded in matchedRules, even
    though only the single highest-urgency (then highest-priority, then
    earliest-listed) match's message is surfaced as the primary result.

    Rules are loaded fresh on every call when `rules` isn't supplied
    (matching the existing appointments.json convention in chatbot_logic.py)
    so an edited rules file takes effect without restarting the process.
    """
    if rules is None:
        rules = load_rules()

    normalized = _normalize(text)

    matches = []
    for rule in rules:
        for keyword in rule["keywords"]:
            if _keyword_pattern(keyword).search(normalized):
                matches.append(rule)
                break  # one matching keyword is enough to count this rule as matched

    if not matches:
        return {
            "urgency": UNKNOWN_URGENCY,
            "matchedRules": [],
            "message": _UNKNOWN_MESSAGE,
            "escalation": _ESCALATION_BY_URGENCY[UNKNOWN_URGENCY],
        }

    # Resolve by urgency severity first, then priority, then - for a fully
    # deterministic tie - whichever matched rule appeared earliest in the
    # rules list. reverse=True + a "-index" key term makes the smallest
    # index win ties, without needing a separate tie-break pass.
    ranked = sorted(
        enumerate(matches),
        key=lambda pair: (_URGENCY_RANK[pair[1]["urgency"]], pair[1]["priority"], -pair[0]),
        reverse=True,
    )
    winner = ranked[0][1]
    matched_ids = [rule["id"] for _, rule in ranked]

    return {
        "urgency": winner["urgency"],
        "matchedRules": matched_ids,
        "message": winner["message"],
        "escalation": _ESCALATION_BY_URGENCY[winner["urgency"]],
    }
