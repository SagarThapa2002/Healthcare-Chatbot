function TypingIndicator() {
  return (
    <div role="status" className="flex items-center gap-2">
      <span className="sr-only">Assistant is typing</span>
      <span
        aria-hidden="true"
        className="flex items-center gap-1 rounded-lg border border-border bg-surface px-3 py-2.5"
      >
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted [animation-delay:150ms] motion-reduce:animate-none" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted [animation-delay:300ms] motion-reduce:animate-none" />
      </span>
    </div>
  );
}

export default TypingIndicator;
