// Small type -> text resolver. All three known types currently render
// identically (plain bubble text); a dedicated booking_confirmation
// presentation can replace its entry here later without ChatPanel or
// MessageList needing to change.
const MESSAGE_TEXT_BY_TYPE = {
  text: (content) => content?.text,
  validation_error: (content) => content?.text,
  booking_confirmation: (content) => content?.text,
};

// Shared with ChatPanel's aria-live announcement so both read a message's
// display text the same way, including the fallback for an unrecognized
// or malformed message type - never throws, never shows "undefined".
function getMessageText(message) {
  if (message.sender === 'user') return message.text;
  const resolve = MESSAGE_TEXT_BY_TYPE[message.type];
  const text = resolve ? resolve(message.content) : undefined;
  return text ?? "I received a response I can't display yet.";
}

function MessageBubble({ message }) {
  const isUser = message.sender === 'user';
  const text = getMessageText(message);

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        role="group"
        aria-label={isUser ? 'You said' : 'Assistant said'}
        className={[
          'max-w-[85%] whitespace-pre-wrap break-words rounded-lg px-4 py-2.5 text-sm leading-relaxed sm:max-w-[75%]',
          isUser
            ? 'bg-primary text-white'
            : 'border border-border bg-surface text-text',
        ].join(' ')}
      >
        {text}
      </div>
    </div>
  );
}

export default MessageBubble;
export { getMessageText };
