function MessageBubble({ message }) {
  const isUser = message.sender === 'user';

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
        {message.text}
      </div>
    </div>
  );
}

export default MessageBubble;
