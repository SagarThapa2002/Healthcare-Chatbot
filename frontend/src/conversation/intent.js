// Simple keyword-based routing for messages that are NOT part of an
// in-progress booking. Not real NLU - see README/notes.
const SYMPTOM_PATTERN = /\b(symptom|headache|fever|pain|cough|dizzy|nausea|sick|hurts|ache)\b/i;

function detectIntent(message) {
  const msg = message.trim().toLowerCase();
  if (msg === 'yes') return 'YesIntent';
  if (msg === 'no') return 'NoIntent';
  if (msg.includes('book')) return 'Book Appointment';
  if (msg.includes('cancel')) return 'Cancel Appointment';
  if (msg.includes('update')) return 'Update Appointment';
  if (msg.includes('view')) return 'View Appointments';
  if (SYMPTOM_PATTERN.test(msg)) return 'Symptom Check';
  return 'General FAQ';
}

// Intents that mean "the user has switched to a different task" while a
// booking is in progress. Deliberately excludes 'Book Appointment' (already
// booking - not a new task) and 'General FAQ' (the default fallback for any
// unparseable text, which should just re-prompt, not cancel the booking).
const INTERRUPTION_INTENTS = ['Symptom Check', 'Cancel Appointment', 'View Appointments', 'Update Appointment'];

export { SYMPTOM_PATTERN, detectIntent, INTERRUPTION_INTENTS };
