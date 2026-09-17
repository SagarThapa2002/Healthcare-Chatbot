// Presentational only. useConversation does not currently expose a distinct
// error state (network/backend failures are caught internally and turned
// into a normal assistant message) - see the Phase 3 report for details.
// This component exists so a real error, once exposed by the hook (or by
// the Phase 4 structured response envelope), has somewhere calm to render
// without inventing a second, UI-only error system in the meantime.
function ErrorBanner({ message }) {
  if (!message) return null;

  return (
    <div
      role="alert"
      className="mb-3 flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2.5 text-sm text-text"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" className="mt-0.5 h-4 w-4 shrink-0 text-danger">
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.75" />
        <path d="M12 8v5m0 3h.01" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
      </svg>
      <p>{message}</p>
    </div>
  );
}

export default ErrorBanner;
