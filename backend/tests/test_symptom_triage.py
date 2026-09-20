"""Tests for backend/symptom_triage.py.

IMPORTANT: every rule below is SYNTHETIC TEST FIXTURE DATA, written only to
exercise matching/validation MECHANICS (word boundaries, multi-word
phrases, priority resolution, etc). None of it is reviewed clinical
guidance, and none of it is used by production backend/symptom_rules.json,
which intentionally contains zero active rules - see
backend/SYMPTOM_RULES_SOURCES.md. Message text below is deliberately
prefixed "TEST MESSAGE" to make this unmistakable.
"""
import json
import os
import tempfile
import unittest

from backend import symptom_triage
from backend.symptom_triage import classify_symptom, load_rules, SymptomRuleError


def make_rule(rule_id, keywords, urgency, priority=0, message=None):
    return {
        "id": rule_id,
        "keywords": keywords,
        "urgency": urgency,
        "priority": priority,
        "message": message or f"TEST MESSAGE for {rule_id} - synthetic fixture, not real clinical guidance.",
        "reference": "synthetic test fixture - not a real clinical source",
    }


EMERGENCY_RULE = make_rule("test-emergency-fever-phrase", ["severe test emergency phrase"], "emergency", priority=10)
URGENT_RULE = make_rule("test-urgent-marker", ["persistent test marker"], "urgent", priority=5)
ROUTINE_RULE = make_rule("test-routine-headache", ["headache"], "routine", priority=0)
GENERAL_RULE = make_rule("test-general-tired", ["tired"], "general", priority=0)
BOUNDARY_RULE = make_rule("test-boundary-ache", ["ache"], "routine", priority=0)
PHRASE_RULE = make_rule("test-phrase-chest-discomfort", ["chest discomfort"], "urgent", priority=0)
PUNCTUATION_RULE = make_rule("test-punctuation-parenthetical", ["pain (mild)"], "routine", priority=0)
METACHARACTER_RULE = make_rule("test-metacharacter-literal", ["zzz.test*mark(x)"], "routine", priority=0)

ALL_FIXTURE_RULES = [
    EMERGENCY_RULE, URGENT_RULE, ROUTINE_RULE, GENERAL_RULE, BOUNDARY_RULE, PHRASE_RULE,
]


def write_rules_file(tmp_dir, rules_obj):
    path = os.path.join(tmp_dir, 'rules.json')
    with open(path, 'w') as f:
        json.dump(rules_obj, f)
    return path


class ClassifySymptomTest(unittest.TestCase):
    def test_known_synthetic_rule_match(self):
        result = classify_symptom("I have a headache", rules=[ROUTINE_RULE])
        self.assertEqual(result["urgency"], "routine")
        self.assertEqual(result["matchedRules"], ["test-routine-headache"])
        self.assertEqual(result["message"], ROUTINE_RULE["message"])
        self.assertEqual(result["escalation"], "self_care")

    def test_each_urgency_category_is_reachable(self):
        cases = [
            ("severe test emergency phrase happening now", "emergency", "emergency_services"),
            ("I have a persistent test marker", "urgent", "book_appointment_soon"),
            ("I have a headache", "routine", "self_care"),
            ("I am tired", "general", "self_care"),
        ]
        for text, expected_urgency, expected_escalation in cases:
            with self.subTest(text=text):
                result = classify_symptom(text, rules=ALL_FIXTURE_RULES)
                self.assertEqual(result["urgency"], expected_urgency)
                self.assertEqual(result["escalation"], expected_escalation)

    def test_unknown_when_nothing_matches(self):
        result = classify_symptom("completely unrelated nonsense input", rules=ALL_FIXTURE_RULES)
        self.assertEqual(result["urgency"], "unknown")
        self.assertEqual(result["matchedRules"], [])
        self.assertEqual(result["escalation"], "none")
        self.assertIn("emergency", result["message"].lower())

    def test_unknown_is_not_silently_general_or_routine(self):
        result = classify_symptom("", rules=ALL_FIXTURE_RULES)
        self.assertEqual(result["urgency"], "unknown")
        self.assertNotEqual(result["urgency"], "general")
        self.assertNotEqual(result["urgency"], "routine")

    def test_multiple_matches_are_all_recorded(self):
        result = classify_symptom("I have a headache and I am tired", rules=ALL_FIXTURE_RULES)
        self.assertIn("test-routine-headache", result["matchedRules"])
        self.assertIn("test-general-tired", result["matchedRules"])

    def test_emergency_outranks_routine_when_both_match(self):
        text = "I have a headache and also severe test emergency phrase happening"
        result = classify_symptom(text, rules=ALL_FIXTURE_RULES)
        self.assertEqual(result["urgency"], "emergency")
        self.assertEqual(result["matchedRules"][0], "test-emergency-fever-phrase")
        self.assertIn("test-routine-headache", result["matchedRules"])

    def test_same_urgency_priority_resolution(self):
        higher = make_rule("same-tier-higher", ["zsymptomone"], "routine", priority=5)
        lower = make_rule("same-tier-lower", ["zsymptomtwo"], "routine", priority=1)
        result = classify_symptom("zsymptomone zsymptomtwo", rules=[lower, higher])
        self.assertEqual(result["matchedRules"][0], "same-tier-higher")
        self.assertEqual(result["message"], higher["message"])

    def test_deterministic_tie_resolution_uses_list_order(self):
        first = make_rule("tie-first", ["zsymptomtie"], "routine", priority=0)
        second = make_rule("tie-second", ["zsymptomtie"], "routine", priority=0)
        result = classify_symptom("zsymptomtie", rules=[first, second])
        self.assertEqual(result["matchedRules"][0], "tie-first")

        # Reversing the list order changes which rule wins - proving the
        # winner is determined by position, not by ID, dict hashing, etc.
        result_reversed = classify_symptom("zsymptomtie", rules=[second, first])
        self.assertEqual(result_reversed["matchedRules"][0], "tie-second")

    def test_word_boundary_true_positive(self):
        result = classify_symptom("I have an ache in my leg", rules=[BOUNDARY_RULE])
        self.assertEqual(result["urgency"], "routine")
        self.assertEqual(result["matchedRules"], ["test-boundary-ache"])

    def test_word_boundary_false_positive_resistance(self):
        # "mustache" contains "ache" as a raw substring ("must" + "ache") -
        # word-boundary matching must not treat this as a match.
        result = classify_symptom("He has a mustache", rules=[BOUNDARY_RULE])
        self.assertEqual(result["urgency"], "unknown")
        self.assertEqual(result["matchedRules"], [])

    def test_false_positive_resistance_retired_vs_tired(self):
        # "retired" contains "tired" as a raw substring.
        result = classify_symptom("I just retired from work", rules=[GENERAL_RULE])
        self.assertEqual(result["urgency"], "unknown")

    def test_multi_word_phrase_matches_as_a_whole(self):
        result = classify_symptom("I have chest discomfort today", rules=[PHRASE_RULE])
        self.assertEqual(result["urgency"], "urgent")
        self.assertEqual(result["matchedRules"], ["test-phrase-chest-discomfort"])

    def test_multi_word_phrase_does_not_match_partial_words(self):
        # Only "chest" is present, not the full phrase "chest discomfort".
        result = classify_symptom("I have a chest cold", rules=[PHRASE_RULE])
        self.assertEqual(result["urgency"], "unknown")

    def test_case_and_whitespace_insensitive(self):
        result = classify_symptom("   I HAVE A   HEADACHE   ", rules=[ROUTINE_RULE])
        self.assertEqual(result["urgency"], "routine")

    def test_deterministic_repeated_results(self):
        text = "I have a headache and also severe test emergency phrase happening"
        first = classify_symptom(text, rules=ALL_FIXTURE_RULES)
        second = classify_symptom(text, rules=ALL_FIXTURE_RULES)
        self.assertEqual(first, second)

    def test_escalation_derivation_for_every_urgency(self):
        self.assertEqual(
            classify_symptom("severe test emergency phrase", rules=[EMERGENCY_RULE])["escalation"],
            "emergency_services",
        )
        self.assertEqual(
            classify_symptom("persistent test marker", rules=[URGENT_RULE])["escalation"],
            "book_appointment_soon",
        )
        self.assertEqual(classify_symptom("headache", rules=[ROUTINE_RULE])["escalation"], "self_care")
        self.assertEqual(classify_symptom("tired", rules=[GENERAL_RULE])["escalation"], "self_care")
        self.assertEqual(classify_symptom("xyz-nothing", rules=[GENERAL_RULE])["escalation"], "none")

    def test_safety_messaging_does_not_claim_certainty(self):
        # A soft content guard, not exhaustive proof: none of the fixture
        # messages should use first-person-certain diagnostic phrasing.
        for rule in ALL_FIXTURE_RULES:
            with self.subTest(rule=rule["id"]):
                self.assertNotIn("you have", rule["message"].lower())
        self.assertNotIn("you have", symptom_triage._UNKNOWN_MESSAGE.lower())

    def test_emergency_message_directs_to_emergency_care(self):
        result = classify_symptom("severe test emergency phrase", rules=[EMERGENCY_RULE])
        self.assertIn("emergency", result["message"].lower())

    def test_punctuation_containing_keyword_matches_literally(self):
        # Regression test for the Phase 5.3 verification finding: a keyword
        # ending in punctuation (here, a closing paren) must still match
        # when literally present, even though the character right after it
        # in the text (a space) is also non-word - a plain \b cannot fire
        # at a non-word/non-word position, but this must still match.
        result = classify_symptom("I have pain (mild) today", rules=[PUNCTUATION_RULE])
        self.assertEqual(result["urgency"], "routine")
        self.assertEqual(result["matchedRules"], ["test-punctuation-parenthetical"])

    def test_punctuation_containing_keyword_rejects_embedded_form(self):
        # The same phrase embedded inside larger words on both sides
        # ("prepain (mild)ish") must NOT match - this is not the phrase
        # standing alone, and matching it would reintroduce the kind of
        # false positive word-boundary matching is meant to prevent.
        result = classify_symptom("I have prepain (mild)ish today", rules=[PUNCTUATION_RULE])
        self.assertEqual(result["urgency"], "unknown")
        self.assertEqual(result["matchedRules"], [])

    def test_regex_metacharacters_in_keyword_are_treated_literally(self):
        # Keyword "zzz.test*mark(x)" contains '.', '*', '(', ')' - regex
        # metacharacters. If they weren't escaped, '.' would match any
        # character and '*' would mean "zero or more of the preceding
        # character", so a DIFFERENT string could incorrectly match.
        literal_match = classify_symptom("value is zzz.test*mark(x) here", rules=[METACHARACTER_RULE])
        self.assertEqual(literal_match["urgency"], "routine")

        # If '.' and '*' were live regex syntax instead of literal
        # characters, "zzzXtestQQQmark(x)" would satisfy
        # "zzz" + any-char + "test" + zero-or-more-Q + "mark(x)" -like
        # reasoning; with correct escaping it must not match at all.
        not_a_match = classify_symptom("value is zzzXtestQQQmark(x) here", rules=[METACHARACTER_RULE])
        self.assertEqual(not_a_match["urgency"], "unknown")


class LoadRulesValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)

    def test_missing_file_raises(self):
        with self.assertRaises(SymptomRuleError):
            load_rules(path=os.path.join(self.tmp_dir.name, 'does-not-exist.json'))

    def test_malformed_json_raises(self):
        path = os.path.join(self.tmp_dir.name, 'bad.json')
        with open(path, 'w') as f:
            f.write("{not valid json")
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_wrong_top_level_type_raises(self):
        path = write_rules_file(self.tmp_dir.name, ["not", "an", "object"])
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_unsupported_schema_version_raises(self):
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "9.9", "rules": []})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_rules_not_a_list_raises(self):
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "1.0", "rules": "oops"})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_missing_required_field_raises(self):
        bad_rule = make_rule("bad", ["x"], "routine")
        del bad_rule["priority"]
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "1.0", "rules": [bad_rule]})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_invalid_urgency_raises(self):
        bad_rule = make_rule("bad", ["x"], "critical")
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "1.0", "rules": [bad_rule]})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_unknown_cannot_be_used_as_a_rule_urgency(self):
        bad_rule = make_rule("bad", ["x"], "unknown")
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "1.0", "rules": [bad_rule]})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_invalid_keywords_not_a_list_raises(self):
        bad_rule = make_rule("bad", "not-a-list", "routine")
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "1.0", "rules": [bad_rule]})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_invalid_keywords_empty_list_raises(self):
        bad_rule = make_rule("bad", [], "routine")
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "1.0", "rules": [bad_rule]})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_invalid_keyword_entry_type_raises(self):
        bad_rule = make_rule("bad", [123], "routine")
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "1.0", "rules": [bad_rule]})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_invalid_priority_type_raises(self):
        bad_rule = make_rule("bad", ["x"], "routine")
        bad_rule["priority"] = "high"
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "1.0", "rules": [bad_rule]})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_priority_true_is_rejected(self):
        # bool is a subclass of int in Python, so a naive `isinstance(x,
        # int)` check alone would silently accept True/False as a
        # priority. Confirms the explicit bool exclusion actually works,
        # round-tripped through real JSON (json.dump/json.load), not just
        # a Python object passed in directly.
        bad_rule = make_rule("bad", ["x"], "routine")
        bad_rule["priority"] = True
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "1.0", "rules": [bad_rule]})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_priority_false_is_rejected(self):
        bad_rule = make_rule("bad", ["x"], "routine")
        bad_rule["priority"] = False
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "1.0", "rules": [bad_rule]})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_missing_reference_raises(self):
        bad_rule = make_rule("bad", ["x"], "routine")
        bad_rule["reference"] = "  "
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "1.0", "rules": [bad_rule]})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_duplicate_rule_ids_raise(self):
        rule_a = make_rule("dup", ["x"], "routine")
        rule_b = make_rule("dup", ["y"], "general")
        path = write_rules_file(self.tmp_dir.name, {"schemaVersion": "1.0", "rules": [rule_a, rule_b]})
        with self.assertRaises(SymptomRuleError):
            load_rules(path=path)

    def test_valid_file_loads_successfully(self):
        path = write_rules_file(
            self.tmp_dir.name, {"schemaVersion": "1.0", "rules": [ROUTINE_RULE]}
        )
        rules = load_rules(path=path)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["id"], "test-routine-headache")


class ProductionRulesFileTest(unittest.TestCase):
    """Enforces the Phase 5.3 safety requirement: production rules must stay
    empty until clinically reviewed and sourced. If this test ever needs to
    change, that change must be a deliberate, reviewed decision to add a
    real, sourced rule - not an accident.
    """

    def test_production_file_is_valid_and_has_zero_active_rules(self):
        rules = load_rules()  # loads the real backend/symptom_rules.json
        self.assertEqual(rules, [])

    def test_production_file_resolves_every_input_to_unknown(self):
        result = classify_symptom("I have a headache and chest pain")
        self.assertEqual(result["urgency"], "unknown")


if __name__ == '__main__':
    unittest.main()
