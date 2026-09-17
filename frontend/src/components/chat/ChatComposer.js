function ChatComposer({ value, onChange, onSubmit, disabled }) {
  const canSend = value.trim().length > 0 && !disabled;

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (canSend) {
        onSubmit(e);
      }
    }
  };

  return (
    <form onSubmit={onSubmit} className="flex items-end gap-2">
      <div className="flex-1">
        <label htmlFor="chat-message-input" className="sr-only">
          Message
        </label>
        <textarea
          id="chat-message-input"
          name="message"
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder="Type your message..."
          className="block max-h-32 w-full resize-none overflow-y-auto rounded-md border border-border bg-background px-3 py-2.5 text-sm text-text placeholder:text-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30 disabled:cursor-not-allowed disabled:opacity-60"
        />
      </div>
      <button
        type="submit"
        disabled={!canSend}
        className="shrink-0 rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50"
      >
        Send
      </button>
    </form>
  );
}

export default ChatComposer;
