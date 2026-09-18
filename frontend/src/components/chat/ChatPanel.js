import { useEffect, useRef } from 'react';
import MessageList from './MessageList';
import { getMessageText } from './MessageBubble';
import EmptyState from './EmptyState';
import TypingIndicator from './TypingIndicator';
import ChatComposer from './ChatComposer';
import ErrorBanner from './ErrorBanner';

function ChatPanel({ messages, userInput, setUserInput, isTyping, sendMessage, error }) {
  const scrollRef = useRef(null);
  const isNearBottomRef = useRef(true);
  const pendingSuggestionRef = useRef(false);

  // Auto-scroll to the latest message, but only when the user was already
  // near the bottom - so reading older messages isn't interrupted.
  useEffect(() => {
    const node = scrollRef.current;
    if (node && isNearBottomRef.current) {
      node.scrollTop = node.scrollHeight;
    }
  }, [messages, isTyping]);

  const handleScroll = (e) => {
    const node = e.currentTarget;
    const distanceFromBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
    isNearBottomRef.current = distanceFromBottom < 120;
  };

  // Bridges a suggestion click into the existing sendMessage flow. sendMessage
  // reads userInput from the hook's own state (not from an argument), so the
  // value has to land in state first and only then be submitted on the next
  // render - this does not add a second submission path, it just sequences
  // the two existing hook calls (setUserInput, sendMessage) correctly.
  useEffect(() => {
    if (pendingSuggestionRef.current) {
      pendingSuggestionRef.current = false;
      sendMessage({ preventDefault: () => {} });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userInput]);

  const handleSuggestionSelect = (value) => {
    pendingSuggestionRef.current = true;
    setUserInput(value);
  };

  const latestAssistantText = (() => {
    if (isTyping) return '';
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].sender === 'bot') return getMessageText(messages[i]);
    }
    return '';
  })();

  return (
    <section
      aria-label="Chat"
      className="flex h-full max-h-[75vh] min-h-[420px] flex-1 flex-col rounded-lg border border-border bg-surface"
    >
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto px-4 py-4 sm:px-6">
        <ErrorBanner message={error} />
        {messages.length === 0 ? (
          <EmptyState onSuggestionSelect={handleSuggestionSelect} disabled={isTyping} />
        ) : (
          <MessageList messages={messages} />
        )}
        {isTyping && (
          <div className="mt-3">
            <TypingIndicator />
          </div>
        )}
      </div>

      {/* Announces the newest assistant reply only - not the whole transcript. */}
      <div aria-live="polite" className="sr-only">
        {latestAssistantText}
      </div>

      <div className="border-t border-border p-3 sm:p-4">
        <ChatComposer value={userInput} onChange={setUserInput} onSubmit={sendMessage} disabled={isTyping} />
      </div>
    </section>
  );
}

export default ChatPanel;
