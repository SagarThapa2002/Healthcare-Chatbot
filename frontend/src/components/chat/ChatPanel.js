import { useEffect, useRef } from 'react';
import MessageList from './MessageList';
import { getMessageText } from './MessageBubble';
import EmptyState from './EmptyState';
import SuggestionChips from './SuggestionChips';
import TypingIndicator from './TypingIndicator';
import ChatComposer from './ChatComposer';
import ErrorBanner from './ErrorBanner';

function ChatPanel({ messages, userInput, setUserInput, isTyping, sendMessage, error }) {
  const scrollRef = useRef(null);
  const isNearBottomRef = useRef(true);
  const pendingSuggestionRef = useRef(false);
  const composerInputRef = useRef(null);
  // Set when a message is sent from the composer or a suggestion chip, so
  // focus can go back to the composer once the reply arrives (see below).
  const restoreFocusRef = useRef(false);
  const wasTypingRef = useRef(isTyping);

  // While a request is pending the composer is disabled, and browsers move
  // focus off a disabled element (a clicked chip is removed outright), so a
  // keyboard user would have to click back in after every message. When the
  // request finishes, focus returns to the composer - but only if this send
  // came from the composer or a chip AND focus is now nowhere (the page
  // body). If the user moved to another control meanwhile, it is left there.
  useEffect(() => {
    const finished = wasTypingRef.current && !isTyping;
    wasTypingRef.current = isTyping;
    if (!finished || !restoreFocusRef.current) return;
    restoreFocusRef.current = false;
    const active = document.activeElement;
    if (!active || active === document.body) {
      composerInputRef.current?.focus();
    }
  }, [isTyping]);

  const handleComposerSubmit = (e) => {
    restoreFocusRef.current = true;
    sendMessage(e);
  };

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
    restoreFocusRef.current = true;
    setUserInput(value);
  };

  // Backend-provided suggestions (e.g. one {id, label, value} per candidate
  // appointment during update/cancel disambiguation) are shown only for the
  // latest message, and only if that message is the bot's. Once the user
  // replies, their message becomes the latest one, so older chips disappear
  // and a stale value can never be sent out of context.
  const latestMessage = messages[messages.length - 1];
  const latestSuggestions =
    latestMessage?.sender === 'bot' && Array.isArray(latestMessage.suggestions)
      ? latestMessage.suggestions
      : [];

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
        {messages.length === 0 ? (
          <EmptyState onSuggestionSelect={handleSuggestionSelect} disabled={isTyping} />
        ) : (
          <MessageList messages={messages} />
        )}
        {latestSuggestions.length > 0 && (
          <div className="mt-3">
            <SuggestionChips
              suggestions={latestSuggestions}
              onSelect={handleSuggestionSelect}
              disabled={isTyping}
            />
          </div>
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
        <ErrorBanner message={error} />
        <ChatComposer
          value={userInput}
          onChange={setUserInput}
          onSubmit={handleComposerSubmit}
          disabled={isTyping}
          inputRef={composerInputRef}
        />
      </div>
    </section>
  );
}

export default ChatPanel;
