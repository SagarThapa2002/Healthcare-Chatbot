import SuggestionChips from './SuggestionChips';

// "Check a symptom" (singular) is deliberate: the existing SYMPTOM_PATTERN
// regex in src/conversation/intent.js is `\bsymptom\b`, which does not match
// the plural "symptoms". This wording is chosen so the shortcut actually
// routes through the existing, unmodified intent detection correctly.
const STARTER_SUGGESTIONS = [
  { id: 'book', label: 'Book an appointment', value: 'Book an appointment' },
  { id: 'symptom', label: 'Check a symptom', value: 'Check a symptom' },
  { id: 'general', label: 'General health question', value: 'General health question' },
];

function EmptyState({ onSuggestionSelect, disabled }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-4 py-8 text-center">
      <div>
        <h2 className="text-base font-semibold text-text">How can I help today?</h2>
        <p className="mx-auto mt-2 max-w-sm text-sm text-muted">
          Ask a general health question, check a symptom, or book an appointment.
          General health information only - this chatbot does not provide a diagnosis.
        </p>
      </div>
      <SuggestionChips suggestions={STARTER_SUGGESTIONS} onSelect={onSuggestionSelect} disabled={disabled} />
    </div>
  );
}

export default EmptyState;
