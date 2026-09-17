import MessageBubble from './MessageBubble';

function MessageList({ messages }) {
  return (
    <div className="flex flex-col gap-3">
      {messages.map((message, idx) => (
        // Messages have no id from useConversation and are append-only, so
        // the index is a stable, safe key here.
        <MessageBubble key={idx} message={message} />
      ))}
    </div>
  );
}

export default MessageList;
