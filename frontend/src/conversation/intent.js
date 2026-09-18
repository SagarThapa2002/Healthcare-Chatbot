// Simple keyword-based routing for messages that are NOT part of an
// in-progress booking. Not real NLU - see README/notes.
const SYMPTOM_PATTERN = /\b(symptom|headache|fever|pain|cough|dizzy|nausea|sick|hurts|ache)\b/i;

// Confidence tiers describe how SPECIFIC the matching rule that fired is -
// e.g. an exact-string match can't be confused with anything else, while an
// unanchored substring check ("book" matching inside "overview") can. This
// is NOT a probability and NOT a machine-learned score: there is no model,
// no training data, and no statistical estimate behind it. It is a fixed,
// hard-coded property of each rule below, assigned once by hand:
//
//   high   - the entire (trimmed, lowercased) message equals a known
//            control word. Nothing else in the message can conflict.
//   medium - a word-boundary-anchored keyword/regex match. Can't match
//            inside an unrelated longer word, but is still a fixed
//            keyword list, not true language understanding.
//   low    - an unanchored substring match. Demonstrated to produce false
//            positives (e.g. "overview" contains "view") - see
//            intent.test.js for pinned examples.
//   none   - no rule matched; this is the unconditional General FAQ
//            fallback, used both for genuine general questions and for
//            anything the classifier simply doesn't recognize.
const CONFIDENCE = {
  HIGH: 'high',
  MEDIUM: 'medium',
  LOW: 'low',
  NONE: 'none',
};

// The single source of truth for intent classification. detectIntent()
// below is a thin wrapper around this - do not duplicate these rules
// anywhere else. Rule order matters: the first rule that matches wins, even
// if a later rule would also match (see the cancel/symptom collision test
// in intent.test.js). This mirrors the original detectIntent if/elif chain
// exactly, so this refactor changes no observable behavior.
function classifyIntent(message) {
  const msg = message.trim().toLowerCase();

  if (msg === 'yes') {
    return { intent: 'YesIntent', confidence: CONFIDENCE.HIGH, reason: 'exact match: "yes"' };
  }
  if (msg === 'no') {
    return { intent: 'NoIntent', confidence: CONFIDENCE.HIGH, reason: 'exact match: "no"' };
  }
  if (msg.includes('book')) {
    return {
      intent: 'Book Appointment',
      confidence: CONFIDENCE.LOW,
      reason: 'unanchored substring match: "book"',
    };
  }
  if (msg.includes('cancel')) {
    return {
      intent: 'Cancel Appointment',
      confidence: CONFIDENCE.LOW,
      reason: 'unanchored substring match: "cancel"',
    };
  }
  if (msg.includes('update')) {
    return {
      intent: 'Update Appointment',
      confidence: CONFIDENCE.LOW,
      reason: 'unanchored substring match: "update"',
    };
  }
  if (msg.includes('view')) {
    return {
      intent: 'View Appointments',
      confidence: CONFIDENCE.LOW,
      reason: 'unanchored substring match: "view"',
    };
  }
  const symptomMatch = msg.match(SYMPTOM_PATTERN);
  if (symptomMatch) {
    return {
      intent: 'Symptom Check',
      confidence: CONFIDENCE.MEDIUM,
      reason: `word-boundary keyword match: "${symptomMatch[0]}"`,
    };
  }

  return {
    intent: 'General FAQ',
    confidence: CONFIDENCE.NONE,
    reason: 'no rule matched - defaulted to General FAQ',
  };
}

// Preserves the exact original detectIntent behavior - every existing
// caller (useConversation.js) is unaffected by this refactor. Not used
// anywhere yet in this phase; runtime routing still calls detectIntent.
function detectIntent(message) {
  return classifyIntent(message).intent;
}

// Intents that mean "the user has switched to a different task" while a
// booking is in progress. Deliberately excludes 'Book Appointment' (already
// booking - not a new task) and 'General FAQ' (the default fallback for any
// unparseable text, which should just re-prompt, not cancel the booking).
const INTERRUPTION_INTENTS = ['Symptom Check', 'Cancel Appointment', 'View Appointments', 'Update Appointment'];

export { SYMPTOM_PATTERN, detectIntent, classifyIntent, CONFIDENCE, INTERRUPTION_INTENTS };
