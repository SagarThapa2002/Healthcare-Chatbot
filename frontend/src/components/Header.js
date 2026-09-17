function Header() {
  return (
    <header className="border-b border-border bg-surface">
      <div className="mx-auto flex w-full max-w-4xl items-center gap-3 px-4 py-4 sm:px-6 lg:px-8">
        <span
          aria-hidden="true"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-white"
        >
          <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5">
            <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
          </svg>
        </span>
        <div>
          <h1 className="text-lg font-semibold leading-tight text-text">Healthcare Chatbot</h1>
          <p className="text-sm leading-tight text-muted">
            General health information &amp; appointment assistant
          </p>
        </div>
      </div>
    </header>
  );
}

export default Header;
