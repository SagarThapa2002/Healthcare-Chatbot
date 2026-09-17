// Generic suggestion list: takes {id, label, value} items and reports the
// selected value via onSelect. Knows nothing about intents, bookings, or
// where its suggestions came from - static text today, structured backend
// suggestions later (Phase 4) without this component changing.
function SuggestionChips({ suggestions, onSelect, disabled }) {
  if (!suggestions || suggestions.length === 0) return null;

  return (
    <div role="group" aria-label="Suggested messages" className="flex flex-wrap justify-center gap-2">
      {suggestions.map((suggestion) => (
        <button
          key={suggestion.id ?? suggestion.value}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(suggestion.value)}
          className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:border-primary hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {suggestion.label}
        </button>
      ))}
    </div>
  );
}

export default SuggestionChips;
