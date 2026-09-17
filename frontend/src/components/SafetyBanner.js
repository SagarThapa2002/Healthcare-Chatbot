function SafetyBanner() {
  return (
    <footer aria-label="Safety information" className="border-t border-warning/40 bg-warning/10">
      <div className="mx-auto flex w-full max-w-4xl items-start gap-2 px-4 py-3 text-sm text-text sm:px-6 lg:px-8">
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          fill="none"
          className="mt-0.5 h-5 w-5 shrink-0 text-warning"
        >
          <path
            d="M12 9v4m0 4h.01M10.29 3.86l-8.18 14.18A2 2 0 0 0 3.83 21h16.34a2 2 0 0 0 1.72-2.96L13.71 3.86a2 2 0 0 0-3.42 0z"
            stroke="currentColor"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <p>
          <strong className="font-semibold">For general health information only.</strong>{' '}
          This chatbot does not provide a diagnosis. If you think you may have a medical
          emergency, contact emergency services immediately.
        </p>
      </div>
    </footer>
  );
}

export default SafetyBanner;
