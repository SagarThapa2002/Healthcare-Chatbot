"""Emergency signposting (backend/emergency_signposting.py) and where it runs.

A small, sourced set of red-flag phrases gets a fixed reply pointing to 999,
NHS 111 or Samaritans, before the ordinary symptom reply and before any LLM
call. These tests pin the four messages that previously got an unsafe reply
("keep an eye on it" or a greeting), the matching rules, the routing, and the
safety properties of every reply.

All data files are redirected to a temp directory; the real backend/*.json
files are never read or written.
"""
import json
import logging
import os
import re
import tempfile
import unittest
from unittest.mock import patch

from app import app
from backend import assistant_service, chatbot_logic, claude_provider, emergency_signposting, llm_config
from backend.emergency_signposting import CRISIS, PHYSICAL_EMERGENCY, POISONING, match_categories, signpost

# The messages from the safety inspection, with the intent the frontend's
# classifier actually sends them as (frontend/src/conversation/intent.js:
# "pain" is a symptom keyword; the others fall through to General FAQ).
REGRESSIONS = [
    ("Symptom Check", "symptom", "I have crushing chest pain and my left arm is numb", PHYSICAL_EMERGENCY),
    ("General FAQ", "message", "I can't breathe", PHYSICAL_EMERGENCY),
    ("General FAQ", "message", "I want to kill myself", CRISIS),
    ("General FAQ", "message", "my child swallowed bleach", POISONING),
]

ORDINARY = [
    "I have a headache",
    "I've had a sore throat and a cough for two days",
    "I feel a bit sad today",
    "I'm tired all the time",
    "I'm a little short of breath after running",
    "What is a balanced diet?",
    "I want to diet and lose weight",
    "Should I bleach my hair?",
    "My payment is overdue",
    "I'm cutting down on sugar",
    "My chest is fine and I can breathe normally now",
    "My lip balm is blue",
    "hello",
    "Sagar",
]

UNSAFE_PHRASES = re.compile(
    r"keep an eye|wait and see|monitor|probably|nothing to worry|\byou (?:probably |likely |may |might )?have (?:a|an)\b|diagnos"
    r"|\bmg\b|paracetamol|aspirin|ibuprofen|lie down|drink water|induce",
    re.IGNORECASE,
)


class MatchingTest(unittest.TestCase):
    def test_the_inspection_messages_match_the_expected_category(self):
        for _, _, message, category in REGRESSIONS:
            with self.subTest(message=message):
                self.assertEqual(match_categories(message)[0], category)

    def test_physical_emergency_phrases(self):
        for message in [
            "crushing chest pain", "Severe chest pain", "a heavy pain in my chest",
            "my chest feels tight", "my chest is really heavy", "tight chest",
            "chest pain going down my left arm", "chest pain and my jaw aches",
            "I cannot breathe", "I can not breathe", "cant breathe", "he is struggling to breathe",
            "severe difficulty breathing", "gasping for air", "my baby is choking",
            "she's not breathing", "he stopped breathing", "his lips are turning blue",
            "my dad is unconscious", "she is unresponsive",
        ]:
            with self.subTest(message=message):
                self.assertEqual(match_categories(message), [PHYSICAL_EMERGENCY])

    def test_poisoning_phrases(self):
        for message in [
            "my child swallowed bleach", "he drank some weed killer", "she ate a button battery",
            "my son swallowed a cleaning product", "I took an overdose", "she has overdosed",
            "I took too many pills", "he swallowed too many painkillers",
        ]:
            with self.subTest(message=message):
                self.assertEqual(match_categories(message)[0], POISONING)

    def test_crisis_phrases(self):
        for message in [
            "I want to kill myself", "I want to end my life", "thinking of taking my own life",
            "I'm going to take my life", "I feel suicidal", "I want to die",
            "I don't want to live anymore", "i dont want to be alive", "I do not want to live",
            "I keep hurting... I want to hurt myself", "I cut myself", "I've been self-harming",
            "self harm",
        ]:
            with self.subTest(message=message):
                self.assertEqual(match_categories(message), [CRISIS])

    def test_case_and_punctuation_do_not_matter(self):
        for message in [
            "I CAN'T BREATHE!!!", "i   cant    breathe", "I can’t breathe", "Crushing chest-pain...",
            "I want to KILL MYSELF.", "my child swallowed BLEACH?!", "Self-Harm",
        ]:
            with self.subTest(message=message):
                self.assertTrue(match_categories(message))

    def test_normalize_lowercases_straightens_apostrophes_and_splits_punctuation(self):
        normalize = emergency_signposting._normalize
        self.assertEqual(normalize("Crushing   Chest-Pain!!!"), "crushing chest pain")
        self.assertEqual(normalize("I can\u2019t \u2018breathe\u2019?!"), "i can't 'breathe'")
        self.assertEqual(normalize("Self-Harm..."), "self harm")
        self.assertEqual(normalize("  my\tchild\n swallowed,bleach  "), "my child swallowed bleach")

    def test_ordinary_messages_do_not_match(self):
        for message in ORDINARY:
            with self.subTest(message=message):
                self.assertEqual(match_categories(message), [])
                self.assertIsNone(signpost(message))

    def test_plain_chest_pain_without_a_red_flag_qualifier_is_not_matched(self):
        # Deliberate, per the NHS heart attack page: the 999 signs are chest
        # pain that is tight/heavy/squeezing or spreads to the arms, neck or
        # jaw. Plain "chest pain" gets the ordinary symptom reply, which
        # itself points to NHS 111 and 999.
        self.assertEqual(match_categories("I have some chest pain"), [])

    def test_non_text_and_empty_input_never_match(self):
        for value in [None, "", "   ", 42, ["I can't breathe"], {"text": "kill myself"}]:
            with self.subTest(value=value):
                self.assertEqual(match_categories(value), [])
                self.assertIsNone(signpost(value))

    def test_crisis_wording_alongside_a_physical_red_flag_adds_samaritans(self):
        reply = signpost("I took an overdose because I want to die")
        self.assertTrue(reply.startswith(emergency_signposting._REPLIES[POISONING]))
        self.assertIn("116 123", reply)


class ReplySafetyTest(unittest.TestCase):
    REPLIES = emergency_signposting._REPLIES

    def test_every_reply_points_to_999_and_says_it_is_not_an_emergency_service(self):
        for category, reply in self.REPLIES.items():
            with self.subTest(category=category):
                self.assertIn("999", reply)
                self.assertIn("not an emergency service", reply)
                self.assertIn("UK numbers", reply)

    def test_category_specific_signposting(self):
        self.assertIn("NHS 111", self.REPLIES[PHYSICAL_EMERGENCY])
        self.assertIn("NHS 111", self.REPLIES[POISONING])
        self.assertIn("116 123", self.REPLIES[CRISIS])
        self.assertIn("Samaritans", self.REPLIES[CRISIS])
        self.assertIn("mental health option", self.REPLIES[CRISIS])

    def test_no_reply_reassures_diagnoses_or_gives_treatment(self):
        for category, reply in self.REPLIES.items():
            with self.subTest(category=category):
                self.assertIsNone(UNSAFE_PHRASES.search(reply))

    def test_replies_never_echo_the_users_message(self):
        for message in ["my child Zelda swallowed bleach", "Quentin says I can't breathe",
                        "I want to kill myself, Ottoline"]:
            with self.subTest(message=message):
                reply = signpost(message)
                for word in ("Zelda", "Quentin", "Ottoline"):
                    self.assertNotIn(word, reply)


class EmergencyRoutingTest(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        tmp = self.tmp_dir.name
        for name, filename in [('APPOINTMENTS_FILE', 'appointments.json'), ('PENDING_FILE', 'pending.json'),
                               ('PENDING_UPDATE_FILE', 'pending_update.json'),
                               ('PENDING_CANCELLATION_FILE', 'pending_cancellation.json')]:
            patcher = patch.object(chatbot_logic, name, os.path.join(tmp, filename))
            patcher.start()
            self.addCleanup(patcher.stop)
        # The LLM is switched ON for every routing test, so "never reaches the
        # LLM" is proven against a path that would otherwise call it.
        patch.object(llm_config, 'LLM_ENABLED', True).start()
        self.addCleanup(patch.stopall)
        self.answer = patch.object(assistant_service, 'answer', wraps=assistant_service.answer).start()
        self.generate = patch.object(claude_provider, 'generate_reply', return_value="General answer.").start()
        self.client = app.test_client()

    def post(self, intent, parameters):
        body = {"queryResult": {"intent": {"displayName": intent}, "parameters": parameters}}
        return self.client.post('/webhook/webhook', json=body).get_json()

    def test_the_inspection_messages_get_signposting_and_never_reach_the_llm(self):
        for intent, key, message, category in REGRESSIONS:
            with self.subTest(message=message):
                response = self.post(intent, {key: message})
                self.assertTrue(response["success"])
                self.assertEqual(response["context"], {"intent": intent})
                self.assertEqual(len(response["messages"]), 1)
                self.assertEqual(response["messages"][0]["type"], "text")
                self.assertEqual(response["messages"][0]["content"]["text"], emergency_signposting._REPLIES[category])
                self.assertEqual(response["messages"][0]["suggestions"], [])
        self.answer.assert_not_called()
        self.generate.assert_not_called()

    def test_a_red_flag_is_caught_on_either_path(self):
        for intent, key in [("Symptom Check", "symptom"), ("General FAQ", "message")]:
            for message in ["I can't breathe", "my chest feels tight", "I want to kill myself"]:
                with self.subTest(intent=intent, message=message):
                    text = self.post(intent, {key: message})["messages"][0]["content"]["text"]
                    self.assertEqual(text, signpost(message))
        self.answer.assert_not_called()
        self.generate.assert_not_called()

    def test_ordinary_general_questions_still_reach_the_llm(self):
        response = self.post("General FAQ", {"message": "What is a balanced diet?"})
        self.assertEqual(response["messages"][0]["content"]["text"], "General answer.")
        self.answer.assert_called_once()
        self.generate.assert_called_once()

    def test_ordinary_symptoms_get_the_generic_signposting_reply(self):
        response = self.post("Symptom Check", {"symptom": "I have a headache since Tuesday, Wilhelmina"})
        text = response["messages"][0]["content"]["text"]
        self.assertEqual(
            text,
            "Thanks for telling me. I can't diagnose symptoms or tell you what's causing them. "
            "If you're worried, or your symptoms are getting worse or not improving, contact your "
            "GP or call NHS 111. If you think it's an emergency, call 999. (UK numbers.)",
        )
        self.assertNotIn("Wilhelmina", text)
        self.assertNotIn("headache", text)
        self.assertNotIn("keep an eye", text.lower())
        self.answer.assert_not_called()

    def test_a_symptom_request_without_a_symptom_is_unchanged(self):
        response = self.post("Symptom Check", {})
        self.assertEqual(
            response["messages"][0]["content"]["text"],
            "Could you please tell me your symptom so I can assist you better?",
        )

    def test_intents_without_free_text_are_never_checked(self):
        # Booking, cancel, update, view, yes and no carry no free text, so the
        # guard never runs for them - a booking name is just a name (a known,
        # documented limitation; see backend/SYMPTOM_RULES_SOURCES.md).
        with patch.object(emergency_signposting, 'signpost', wraps=emergency_signposting.signpost) as spy:
            name_reply = self.post("Book Appointment", {"name": "Sagar"})
            self.assertEqual(name_reply["context"]["bookingStage"], "provider")
            self.post("Book Appointment", {"name": "I can't breathe"})
            self.post("View Appointments", {})
            self.post("YesIntent", {})
            self.post("NoIntent", {})
            self.post("Cancel Appointment", {"name": "kill myself"})
            self.post("Update Appointment", {"name": "kill myself"})
        spy.assert_not_called()

    def test_the_users_text_is_never_logged(self):
        with self.assertLogs(level=logging.DEBUG) as logs:
            for intent, key, message, _ in REGRESSIONS:
                self.post(intent, {key: message})
        self.assertTrue(logs.output)
        joined = "\n".join(logs.output).lower()
        for _, _, message, _ in REGRESSIONS:
            self.assertNotIn(message.lower(), joined)
        for word in ("bleach", "breathe", "kill", "chest"):
            self.assertNotIn(word, joined)


if __name__ == '__main__':
    unittest.main()
